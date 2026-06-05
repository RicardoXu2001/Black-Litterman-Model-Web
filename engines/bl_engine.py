"""
Black-Litterman 投资组合优化 —— 核心计算引擎
从 web_app.py 提取的纯函数模块，供 API 和回测引擎共用。
"""
import numpy as np
import pandas as pd
import scipy.optimize as sc_optim


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
    """归一化权重，使其总和为 1"""
    weight = _as_float_array(weight, "权重")
    if long_only:
        weight = np.clip(weight, min_weight, max_weight)
    total = weight.sum()
    if abs(total) < 1e-12:
        raise PortfolioInputError("市场均衡权重之和不能为 0。")
    return weight / total


def regularize_covariance(returns, shrinkage=0.1, ridge=1e-8):
    """协方差矩阵正则化：收缩 + 岭回归"""
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
    long_only=True, min_weight=0.0, max_weight=1.0,
    turnover_limit=None, turnover_penalty=0.001,
):
    """带现实约束的权重优化（SLSQP）"""
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
        return previous_weight  # fallback：保持上期权重
    return normalize_weight(result.x, long_only, min_weight, max_weight)


def optimize_portfolio(payload):
    """Black-Litterman 投资组合优化主流程

    参数 (payload dict):
        assets: list[str]              — 资产名称列表
        market_weights: list[float]     — 市场均衡权重
        returns: list[list[float]]      — 历史收益率矩阵 (T x N)
        views: list[dict]               — 投资者观点
        tau: float                      — 缩放尺度
        periods_per_year: int           — 每年期数
        risk_free_rate_annual: float    — 年化无风险利率
        cov_shrinkage: float            — 协方差收缩比例
        cov_ridge: float                — 协方差岭项
        long_only: bool                 — 是否只做多
        min_weight: float               — 单资产最小权重
        max_weight: float               — 单资产最大权重
        turnover_limit: float|None      — 换手率上限
        turnover_penalty: float         — 换手率惩罚系数
        previous_weights: list[float]|None — 上期权重

    返回: dict
    """
    # ── 解析资产 ──
    assets = [str(a).strip() for a in payload.get("assets", []) if str(a).strip()]
    if len(assets) < 2:
        raise PortfolioInputError("至少需要 2 个资产。")
    if len(set(assets)) != len(assets):
        raise PortfolioInputError("资产名称不能重复。")

    # ── 参数 ──
    tau = float(payload.get("tau", 0.3))
    periods_per_year = float(payload.get("periods_per_year", 52))
    risk_free_rate_annual = float(payload.get("risk_free_rate_annual", 0.0324))
    cov_shrinkage = float(payload.get("cov_shrinkage", 0.1))
    cov_ridge = float(payload.get("cov_ridge", 1e-8))
    long_only = bool(payload.get("long_only", True))
    min_weight = float(payload.get("min_weight", 0.0))
    max_weight = float(payload.get("max_weight", 0.35))
    turnover_limit_raw = payload.get("turnover_limit", 0.50)
    turnover_limit = None if turnover_limit_raw in ("", None) else float(turnover_limit_raw)
    turnover_penalty = float(payload.get("turnover_penalty", 0.001))

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
