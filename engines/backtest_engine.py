"""
滚动回测引擎 —— 从 code/back_test.py 重构
不依赖 matplotlib，返回原始数据供前端 Plotly.js 渲染。
"""
import numpy as np
import pandas as pd
from engines.bl_engine import (
    normalize_weight, regularize_covariance,
    constrained_weight, PortfolioInputError,
)


def run_backtest(
    price_df,          # DataFrame: 完整价格历史（index 为整数序号，含 Date 列或已 drop）
    mv_array,          # ndarray: 完整市值权重历史 (T x N)
    assets,            # list[str]: 股票名称列表
    start_idx,         # int: 回测起始索引
    end_idx,           # int: 回测结束索引
    window_T=200,      # int: 滚动窗口大小
    view_type=2,       # int: 观点类型 0-3
    view_T=10,         # int: 近期观点窗口（仅 view_type=3 时使用）
    tau=0.3,
    risk_free_rate_annual=0.0324,
    periods_per_year=52,
    cov_shrinkage=0.1,
    cov_ridge=1e-8,
    long_only=True,
    min_weight=0.0,
    max_weight=0.35,
    turnover_limit=0.50,
    turnover_penalty=0.001,
    transaction_cost_bps=10,
):
    """
    运行滚动回测，返回完整结果字典。

    返回:
        dict:
            dates: list[str]
            gross_accumulated_return: list[float]   — 每期累计（log 收益累计）
            net_accumulated_return: list[float]
            equal_weight_accumulated_return: list[float]
            weights_over_time: list[list[float]]     — 每期权重
            turnover_set: list[float]                — 每期换手率
            transaction_cost_set: list[float]        — 每期交易成本
            summary: dict
    """
    # 准备价格数据：用 log 收益率
    log_ret_df = np.log(price_df / price_df.shift()).dropna()
    log_ret_df.index = range(len(log_ret_df))

    gross_ret_set = []
    net_ret_set = []
    weight_set = []
    turnover_list = []
    cost_list = []
    previous_weight = None

    for cur_idx in range(start_idx, end_idx + 1):
        # 当前期真实收益率
        real_ret = np.array(log_ret_df.loc[cur_idx, assets])

        # 滚动窗口收益率
        window_rets = log_ret_df.loc[cur_idx - window_T: cur_idx - 1, assets]
        if len(window_rets) < len(assets) + 2:
            # 数据不足，保持等权
            w_bl = np.ones(len(assets)) / len(assets)
            gross_ret_set.append(float(np.dot(w_bl, real_ret.T)))
            weight_set.append(w_bl.tolist())
            turnover_list.append(0.0)
            cost_list.append(0.0)
            previous_weight = w_bl
            net_ret_set.append(gross_ret_set[-1])
            continue

        mkt_cov = regularize_covariance(window_rets, cov_shrinkage, cov_ridge)

        # 当前市值权重
        mv_i = mv_array[cur_idx - 1] if cur_idx > 0 else mv_array[0]
        mv_i = normalize_weight(mv_i, long_only, min_weight, max_weight)

        # 风险厌恶 & 先验收益
        rf_period = np.log(1 + risk_free_rate_annual) / periods_per_year
        mean_ret = window_rets.mean().values
        portfolio_var = float(np.dot(np.dot(mv_i, mkt_cov), mv_i.T))
        if portfolio_var <= 0:
            lambd = 1.0
        else:
            lambd = (float(np.dot(mv_i, mean_ret)) - rf_period) / portfolio_var
            if lambd <= 0 or not np.isfinite(lambd):
                lambd = 1.0

        implied_ret = lambd * np.dot(mkt_cov, mv_i)

        # 观点矩阵
        P, Q = _get_views_P_Q(view_type, len(assets), window_rets, view_T)
        if P is not None and Q is not None:
            omega = _get_views_omega(mkt_cov, P, tau)
            inv_tau_cov = np.linalg.pinv(tau * mkt_cov)
            inv_omega = np.linalg.pinv(omega)
            mid = np.linalg.pinv(inv_tau_cov + np.dot(np.dot(P.T, inv_omega), P))
            posterior_ret = np.dot(mid, np.dot(inv_tau_cov, implied_ret) + np.dot(np.dot(P.T, inv_omega), Q))
        else:
            posterior_ret = implied_ret

        # view_type 0: 直接用市值权重
        if view_type == 0:
            w_bl = normalize_weight(mv_i, long_only, min_weight, max_weight)
        else:
            w_bl = constrained_weight(
                posterior_ret, mkt_cov, lambd, previous_weight,
                long_only, min_weight, max_weight,
                turnover_limit, turnover_penalty,
            )

        # 记录
        gross_ret = float(np.dot(w_bl, real_ret.T))
        turnover = 0.0 if previous_weight is None else float(np.sum(np.abs(w_bl - previous_weight)))
        txn_cost = turnover * transaction_cost_bps / 10000
        net_ret = gross_ret - txn_cost

        gross_ret_set.append(gross_ret)
        net_ret_set.append(net_ret)
        weight_set.append(w_bl.tolist())
        turnover_list.append(turnover)
        cost_list.append(txn_cost)
        previous_weight = w_bl

    # 累计收益
    gross_acc = _cumsum(gross_ret_set)
    net_acc = _cumsum(net_ret_set)
    eq_acc = _equal_weight_cumsum(log_ret_df, assets, start_idx, end_idx)

    return {
        "dates": list(range(start_idx, end_idx + 1)),
        "gross_accumulated_return": gross_acc,
        "net_accumulated_return": net_acc,
        "equal_weight_accumulated_return": eq_acc,
        "weights_over_time": weight_set,
        "turnover_set": turnover_list,
        "transaction_cost_set": cost_list,
        "summary": {
            "gross_total_return": round(gross_acc[-1], 6) if gross_acc else 0,
            "net_total_return": round(net_acc[-1], 6) if net_acc else 0,
            "eq_total_return": round(eq_acc[-1], 6) if eq_acc else 0,
            "average_turnover": round(float(np.mean(turnover_list)), 6) if turnover_list else 0,
            "total_transaction_cost": round(float(np.sum(cost_list)), 6) if cost_list else 0,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _cumsum(values):
    acc = [0]
    for v in values:
        acc.append(acc[-1] + v)
    return acc


def _equal_weight_cumsum(log_ret_df, assets, start_idx, end_idx):
    stock_ret = log_ret_df.loc[start_idx:end_idx, assets]
    eq_acc = [0]
    for _, row in stock_ret.iterrows():
        eq_acc.append(eq_acc[-1] + np.mean(row.values))
    return eq_acc


def _get_views_P_Q(view_type, N, stock_cc_ret, view_T=10):
    """构造观点矩阵 P 和 Q（与 CLI 版 black_litterman.py 保持一致）"""
    if view_type == 0:
        return None, None

    elif view_type == 1:
        # 任意观点
        P = np.zeros([3, N])
        P[0, 8] = 1
        P[0, 9] = -1
        P[1, 1] = 1
        P[1, 3] = -1
        P[2, 3] = 0.1
        P[2, 4] = 0.9
        P[2, 6] = -0.1
        P[2, 7] = -0.9
        Q = np.array([0.0001, 0.00025, 0.0001])
        return P, Q

    elif view_type == 2:
        # 合理观点：AMZN 比 JPM 高 1.7%
        P = np.zeros([1, N])
        P[0, 2] = 1
        P[0, 3] = -1
        Q = np.array([0.017])
        return P, Q

    elif view_type == 3:
        # 近期收益作为观点
        T_near = view_T
        P = np.identity(N)
        stock_cc_ret_near = stock_cc_ret.iloc[-T_near:]
        Q = np.array(stock_cc_ret_near.mean())
        return P, Q

    return None, None


def _get_views_omega(mkt_cov, P, tau=0.3):
    K = len(P)
    omega = np.identity(K)
    for i in range(K):
        P_i = P[i]
        omega[i][i] = float(np.dot(np.dot(P_i, mkt_cov), P_i.T) * tau)
    return omega
