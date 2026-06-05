"""
智能投资分析平台 —— Flask Web 应用
Apple 风格中文工作台，面向普通投资者。
"""
import json
import os
import traceback

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

from engines.bl_engine import optimize_portfolio, PortfolioInputError
from engines.backtest_engine import run_backtest
from engines.quant_engine import run_quant_analysis, QuantAnalysisError
from structures import (
    BASE_DIR,
    PRICE_FILENAME, PRICE_SHEETNAME,
    MV_FILENAME, MV_SHEETNAME,
    TAU, PERIODS_PER_YEAR, RISK_FREE_RATE_ANNUAL,
    COV_SHRINKAGE, COV_RIDGE,
    LONG_ONLY, MIN_WEIGHT, MAX_WEIGHT,
    TURNOVER_LIMIT, TURNOVER_PENALTY,
    TRANSACTION_COST_BPS,
    BACK_TEST_T, START_INDEX, END_INDEX,
    VIEW_TYPE, VIEW_T,
    ARIMA_ORDER, MARKOV_N_STATES, FORECAST_STEPS,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)


# ═══════════════════════════════════════════════════════════════════════
# 页面路由
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """首页"""
    return render_template("index.html")


@app.route("/portfolio")
def portfolio():
    """投资组合页"""
    return render_template("portfolio.html")


@app.route("/quant")
def quant():
    """量化分析页"""
    return render_template("quant.html")


# ═══════════════════════════════════════════════════════════════════════
# API：示例数据（投资组合）
# ═══════════════════════════════════════════════════════════════════════

def load_sample_payload():
    """从 Excel 文件加载投资组合示例数据"""
    price_df = pd.read_excel(PRICE_FILENAME, sheet_name=PRICE_SHEETNAME)
    price_df = price_df.set_index("Date").astype("float64")
    returns = np.log(price_df / price_df.shift()).dropna()
    assets = returns.columns.tolist()[3:]  # 去掉前 3 个指数
    stock_returns = returns[assets].tail(200)

    mv_df = pd.read_excel(MV_FILENAME, sheet_name=MV_SHEETNAME)
    mv_df = mv_df.set_index("Date").astype("float64")
    total_col = next((c for c in mv_df.columns if str(c).lower() == "total"), None)
    if total_col is None:
        raise ValueError("Market_Value.xlsx 中未找到 TOTAL 列。")
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


@app.route("/api/sample")
def api_sample():
    """返回投资组合示例数据"""
    try:
        data = load_sample_payload()
        return jsonify({"ok": True, "data": data})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"加载示例失败：{exc}"}), 500


# ═══════════════════════════════════════════════════════════════════════
# API：单次优化
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    """执行 Black-Litterman 单次优化"""
    try:
        payload = request.get_json(force=True)
        result = optimize_portfolio(payload)
        return jsonify({"ok": True, "data": result})
    except PortfolioInputError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"服务器计算失败：{exc}"}), 500


# ═══════════════════════════════════════════════════════════════════════
# API：滚动回测
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    """运行滚动回测"""
    try:
        payload = request.get_json(force=True)
        use_sample = payload.get("use_sample_data", True)

        if use_sample:
            price_df = pd.read_excel(PRICE_FILENAME, sheet_name=PRICE_SHEETNAME)
            price_df = price_df.set_index("Date").astype("float64")
            assets = price_df.columns.tolist()[3:]

            mv_df = pd.read_excel(MV_FILENAME, sheet_name=MV_SHEETNAME)
            mv_df = mv_df.set_index("Date").astype("float64")
            total_col = next((c for c in mv_df.columns if str(c).lower() == "total"), None)
            mv_array = np.array(mv_df[assets].div(mv_df[total_col], axis=0))
        else:
            # 使用上传数据（暂未实现前端上传，预留接口）
            return jsonify({"ok": False, "error": "暂不支持自定义数据，请使用示例数据。"}), 400

        start_idx = int(payload.get("start_idx", START_INDEX))
        end_idx = int(payload.get("end_idx", END_INDEX))
        window_T = int(payload.get("window_T", BACK_TEST_T))
        view_type = int(payload.get("view_type", VIEW_TYPE))

        max_weight = float(payload.get("max_weight", MAX_WEIGHT))
        turnover_limit_raw = payload.get("turnover_limit", TURNOVER_LIMIT)
        turnover_limit = None if turnover_limit_raw in ("", None) else float(turnover_limit_raw)

        result = run_backtest(
            price_df=price_df,
            mv_array=mv_array,
            assets=assets,
            start_idx=start_idx,
            end_idx=end_idx,
            window_T=window_T,
            view_type=view_type,
            view_T=VIEW_T,
            tau=TAU,
            risk_free_rate_annual=RISK_FREE_RATE_ANNUAL,
            periods_per_year=PERIODS_PER_YEAR,
            cov_shrinkage=COV_SHRINKAGE,
            cov_ridge=COV_RIDGE,
            long_only=LONG_ONLY,
            min_weight=MIN_WEIGHT,
            max_weight=max_weight,
            turnover_limit=turnover_limit,
            turnover_penalty=TURNOVER_PENALTY,
            transaction_cost_bps=TRANSACTION_COST_BPS,
        )
        return jsonify({"ok": True, "data": result})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"回测失败：{exc}"}), 500


# ═══════════════════════════════════════════════════════════════════════
# API：量化分析
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/quant/sample")
def api_quant_sample():
    """返回量化分析示例数据（Apple 股价）"""
    try:
        price_df = pd.read_excel(PRICE_FILENAME, sheet_name=PRICE_SHEETNAME)
        price_df = price_df.set_index("Date").astype("float64")
        # 取 AAPL（第一支股票，索引为 3）
        aapl_col = price_df.columns[3]
        aapl_prices = price_df[aapl_col].values
        dates = price_df.index.tolist()

        return jsonify({
            "ok": True,
            "data": {
                "name": aapl_col,
                "dates": dates,
                "prices": aapl_prices.tolist(),
            },
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": f"加载示例失败：{exc}"}), 500


@app.route("/api/quant/analyze", methods=["POST"])
def api_quant_analyze():
    """运行 Markov + ARIMA 量化分析"""
    try:
        payload = request.get_json(force=True)
        prices = payload.get("prices")
        if not prices or len(prices) < 20:
            return jsonify({"ok": False, "error": "价格数据不足（至少需要 20 条）。"}), 400

        arima_order = tuple(payload.get("arima_order", ARIMA_ORDER))
        markov_states = int(payload.get("markov_states", MARKOV_N_STATES))
        forecast_steps = int(payload.get("forecast_steps", FORECAST_STEPS))

        result = run_quant_analysis(
            prices=np.array(prices, dtype=float),
            arima_order=arima_order,
            markov_states=markov_states,
            forecast_steps=forecast_steps,
        )
        return jsonify({"ok": True, "data": result})
    except QuantAnalysisError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"分析失败：{exc}"}), 500


# ═══════════════════════════════════════════════════════════════════════
# 错误处理
# ═══════════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(_error):
    return jsonify({"ok": False, "error": "页面不存在。"}), 404


@app.errorhandler(500)
def server_error(_error):
    return jsonify({"ok": False, "error": "服务器内部错误。"}), 500


# ═══════════════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  智投 —— 智能投资分析平台")
    print("  首页:       http://127.0.0.1:8000")
    print("  投资组合:   http://127.0.0.1:8000/portfolio")
    print("  量化分析:   http://127.0.0.1:8000/quant")
    print("  按 Ctrl+C 停止服务")
    print("=" * 60)
    app.run(host="127.0.0.1", port=8000, debug=True)
