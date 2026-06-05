"""
Black-Litterman 投资组合优化 —— Flask Web 服务
Apple 风格中文工作台后端
"""
import json
import os

import numpy as np
import pandas as pd
import scipy.optimize as sc_optim
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from structures import (
    BASE_DIR,
    PRICE_FILENAME,
    PRICE_SHEETNAME,
    MV_FILENAME,
    MV_SHEETNAME,
    TAU,
    PERIODS_PER_YEAR,
    RISK_FREE_RATE_ANNUAL,
    COV_SHRINKAGE,
    COV_RIDGE,
    LONG_ONLY,
    MIN_WEIGHT,
    MAX_WEIGHT,
    TURNOVER_LIMIT,
    TURNOVER_PENALTY,
)

app = Flask(__name__, static_folder="web/static", static_url_path="")
CORS(app)


# ═══════════════════════════════════════════════════════════════════════
# 自定义异常
# ═══════════════════════════════════════════════════════════════════════

class PortfolioInputError(ValueError):
    """投资组合输入错误"""
    pass


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

def _as_float_array(values, name):
    try:
        arr = np.array(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise PortfolioInputError(f"{name} 必须是数字。") from exc
    if not np.all(np.isfinite(arr)):
        raise PortfolioInputError(f"{name} 不能包含空值或无穷值。")
    return arr


def normalize_weight(weight, long_only=True, min_weight=0.0, max_weight=1.0):
    weight = _as_float_array(weight, "权重")
    if long_only:
        weight = np.clip(weight, min_weight, max_weight)
    total = weight.sum()
    if abs(total) < 1e-12:
        raise PortfolioInputError("市场均衡权重之和不能为 0。")
    return weight / total


def regularize_covariance(returns, shrinkage, ridge):
    cov = np.array(pd.DataFrame(returns).cov())
    if shrinkage > 0:
        diag_cov = np.diag(np.diag(cov))
        cov = (1 - shrinkage) * cov + shrinkage * diag_cov
    return cov + np.identity(cov.shape[0]) * ridge


# ═══════════════════════════════════════════════════════════════════════
# Black-Litterman 核心计算
# ═══════════════════════════════════════════════════════════════════════

def build_views(views, assets, covariance, tau):
    """根据用户输入构造 P、Q、Omega 矩阵"""
    if not views:
        return None, None, None

    asset_index = {asset: idx for idx, asset in enumerate(assets)}
    p_rows = []
    q_values = []
    omega_values = []

    for idx, view in enumerate(views, start=1):
        row = np.zeros(len(assets))
        legs = view.get("legs", [])
        if not legs:
            raise PortfolioInputError(f"观点 {idx} 至少需要一个资产腿。")

        for leg in legs:
            asset = str(leg.get("asset", "")).strip()
            if asset not in asset_index:
                raise PortfolioInputError(f"观点 {idx} 中的资产 {asset} 不在资产列表里。")
            row[asset_index[asset]] += float(leg.get("weight", 0))

        if np.allclose(row, 0):
            raise PortfolioInputError(f"观点 {idx} 的资产权重不能全为 0。")

        q = float(view.get("q", 0))
        confidence = float(view.get("confidence", 0.5))
        confidence = min(max(confidence, 0.01), 1.0)
        view_variance = float(np.dot(np.dot(row, covariance), row.T) * tau)
        omega = max(view_variance / confidence, 1e-10)

        p_rows.append(row)
        q_values.append(q)
        omega_values.append(omega)

    return np.array(p_rows), np.array(q_values), np.diag(omega_values)


def constrained_weight(
    posterior_return, covariance, risk_aversion, previous_weight,
    long_only, min_weight, max_weight, turnover_limit, turnover_penalty,
):
    """带现实约束的权重优化"""
    n_assets = len(posterior_return)
    if previous_weight is None:
        previous_weight = np.ones(n_assets) / n_assets
    previous_weight = normalize_weight(previous_weight, long_only, min_weight, max_weight)

    def objective(weight):
        utility = (
            np.dot(weight, posterior_return)
            - 0.5 * risk_aversion * np.dot(np.dot(weight, covariance), weight.T)
        )
        turnover_cost = turnover_penalty * np.sum(np.abs(weight - previous_weight))
        return -utility + turnover_cost

    bounds = [(min_weight, max_weight)] * n_assets if long_only else [(None, None)] * n_assets
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    if turnover_limit is not None:
        constraints.append({
            "type": "ineq",
            "fun": lambda w: turnover_limit - np.sum(np.abs(w - previous_weight)),
        })

    result = sc_optim.minimize(
        objective, previous_weight, method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 5000, "ftol": 1e-12},
    )
    if not result.success:
        raise PortfolioInputError(f"组合优化失败：{result.message}")
    return normalize_weight(result.x, long_only, min_weight, max_weight)


def optimize_portfolio(payload):
    """Black-Litterman 投资组合优化主流程"""
    # ── 解析资产 ──
    assets = [str(a).strip() for a in payload.get("assets", []) if str(a).strip()]
    if len(assets) < 2:
        raise PortfolioInputError("至少需要 2 个资产。")
    if len(set(assets)) != len(assets):
        raise PortfolioInputError("资产名称不能重复。")

    # ── 参数 ──
    tau = float(payload.get("tau", TAU))
    periods_per_year = float(payload.get("periods_per_year", PERIODS_PER_YEAR))
    risk_free_rate_annual = float(payload.get("risk_free_rate_annual", RISK_FREE_RATE_ANNUAL))
    cov_shrinkage = float(payload.get("cov_shrinkage", COV_SHRINKAGE))
    cov_ridge = float(payload.get("cov_ridge", COV_RIDGE))
    long_only = bool(payload.get("long_only", LONG_ONLY))
    min_weight = float(payload.get("min_weight", MIN_WEIGHT))
    max_weight = float(payload.get("max_weight", MAX_WEIGHT))
    turnover_limit_raw = payload.get("turnover_limit", TURNOVER_LIMIT)
    turnover_limit = None if turnover_limit_raw in ("", None) else float(turnover_limit_raw)
    turnover_penalty = float(payload.get("turnover_penalty", TURNOVER_PENALTY))

    # ── 市场权重 ──
    market_weight = normalize_weight(
        payload.get("market_weights", []), long_only, min_weight, max_weight,
    )
    if len(market_weight) != len(assets):
        raise PortfolioInputError("市场均衡权重数量必须与资产数量一致。")

    if long_only and max_weight * len(assets) < 1:
        raise PortfolioInputError("单资产最大权重过低，所有资产加总无法达到 100%。")

    # ── 历史收益率 ──
    returns = _as_float_array(payload.get("returns", []), "历史收益率矩阵")
    if returns.ndim != 2 or returns.shape[1] != len(assets):
        raise PortfolioInputError("历史收益率矩阵的列数必须与资产数量一致。")
    if returns.shape[0] < len(assets) + 2:
        raise PortfolioInputError("历史收益率样本太少，建议至少大于资产数量。")

    # ── 协方差 & 风险厌恶 ──
    covariance = regularize_covariance(returns, cov_shrinkage, cov_ridge)
    risk_free_period = np.log(1 + risk_free_rate_annual) / periods_per_year
    mean_return = returns.mean(axis=0)
    portfolio_var = float(np.dot(np.dot(market_weight, covariance), market_weight.T))
    if portfolio_var <= 0:
        raise PortfolioInputError("组合方差异常，请检查历史收益率。")

    risk_aversion = (float(np.dot(market_weight, mean_return)) - risk_free_period) / portfolio_var
    if risk_aversion <= 0 or not np.isfinite(risk_aversion):
        risk_aversion = 1.0

    implied_return = risk_aversion * np.dot(covariance, market_weight)

    # ── 观点 → 后验收益 ──
    p_matrix, q_vector, omega = build_views(
        payload.get("views", []), assets, covariance, tau,
    )

    if p_matrix is None:
        posterior_return = implied_return
    else:
        inv_tau_cov = np.linalg.pinv(tau * covariance)
        inv_omega = np.linalg.pinv(omega)
        middle = np.linalg.pinv(inv_tau_cov + np.dot(np.dot(p_matrix.T, inv_omega), p_matrix))
        posterior_return = np.dot(
            middle,
            np.dot(inv_tau_cov, implied_return)
            + np.dot(np.dot(p_matrix.T, inv_omega), q_vector),
        )

    # ── 权重优化 ──
    previous_weight = payload.get("previous_weights")
    if previous_weight is not None and len(previous_weight) == 0:
        previous_weight = None
    if previous_weight is None:
        previous_weight = market_weight

    target_weight = constrained_weight(
        posterior_return, covariance, risk_aversion, previous_weight,
        long_only, min_weight, max_weight, turnover_limit, turnover_penalty,
    )

    # ── 绩效指标 ──
    previous_for_turnover = normalize_weight(previous_weight, long_only, min_weight, max_weight)
    turnover = float(np.sum(np.abs(target_weight - previous_for_turnover)))
    expected_period_return = float(np.dot(target_weight, posterior_return))
    expected_period_vol = float(np.sqrt(np.dot(np.dot(target_weight, covariance), target_weight.T)))
    expected_annual_return = expected_period_return * periods_per_year
    expected_annual_vol = expected_period_vol * np.sqrt(periods_per_year)
    sharpe = (
        (expected_annual_return - risk_free_rate_annual) / expected_annual_vol
        if expected_annual_vol > 0 else 0.0
    )

    return {
        "assets": assets,
        "weights": target_weight.tolist(),
        "market_weights": market_weight.tolist(),
        "implied_returns": implied_return.tolist(),
        "posterior_returns": posterior_return.tolist(),
        "risk_aversion": risk_aversion,
        "turnover": turnover,
        "metrics": {
            "expected_period_return": expected_period_return,
            "expected_period_vol": expected_period_vol,
            "expected_annual_return": expected_annual_return,
            "expected_annual_vol": expected_annual_vol,
            "sharpe": sharpe,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# 示例数据
# ═══════════════════════════════════════════════════════════════════════

def load_sample_payload():
    """从 Excel 文件加载示例数据"""
    price_df = pd.read_excel(PRICE_FILENAME, sheet_name=PRICE_SHEETNAME)
    price_df = price_df.set_index("Date").astype("float64")
    returns = np.log(price_df / price_df.shift()).dropna()
    assets = returns.columns.tolist()[3:]
    stock_returns = returns[assets].tail(200)

    mv_df = pd.read_excel(MV_FILENAME, sheet_name=MV_SHEETNAME)
    mv_df = mv_df.set_index("Date").astype("float64")
    total_col = next((c for c in mv_df.columns if str(c).lower() == "total"), None)
    market_weights = (mv_df[assets].iloc[-1] / mv_df[total_col].iloc[-1]).tolist()

    return {
        "assets": assets,
        "market_weights": market_weights,
        "returns": stock_returns.round(8).values.tolist(),
        "views": [
            {
                "name": "AMZN 相对 JPM",
                "legs": [
                    {"asset": "AMZN.O", "weight": 1},
                    {"asset": "JPM.N", "weight": -1},
                ],
                "q": 0.017,
                "confidence": 0.8,
            }
        ],
        "tau": TAU,
        "periods_per_year": PERIODS_PER_YEAR,
        "risk_free_rate_annual": RISK_FREE_RATE_ANNUAL,
        "cov_shrinkage": COV_SHRINKAGE,
        "long_only": LONG_ONLY,
        "min_weight": MIN_WEIGHT,
        "max_weight": MAX_WEIGHT,
        "turnover_limit": TURNOVER_LIMIT,
        "turnover_penalty": TURNOVER_PENALTY,
    }


# ═══════════════════════════════════════════════════════════════════════
# Flask 路由
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """主页面"""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/sample")
def api_sample():
    """返回示例数据"""
    try:
        data = load_sample_payload()
        return jsonify({"ok": True, "data": data})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"加载示例失败：{exc}"}), 500


@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    """执行 Black-Litterman 优化"""
    try:
        payload = request.get_json(force=True)
        result = optimize_portfolio(payload)
        return jsonify({"ok": True, "data": result})
    except PortfolioInputError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"服务器计算失败：{exc}"}), 500


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"ok": False, "error": "页面不存在。"}), 404


# ═══════════════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Black-Litterman 投资组合优化工作台")
    print("地址: http://127.0.0.1:8000")
    print("按 Ctrl+C 停止服务\n")
    app.run(host="127.0.0.1", port=8000, debug=True)
