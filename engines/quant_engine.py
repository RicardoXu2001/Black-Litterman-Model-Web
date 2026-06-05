"""
量化分析引擎 —— Markov 链 + ARIMA 时间序列模型
识别市场状态（牛/熊/震荡）并预测股价走势。
"""
import numpy as np
import warnings

warnings.filterwarnings("ignore")


class QuantAnalysisError(ValueError):
    """量化分析输入错误"""
    pass


class _SimpleHMM:
    """HMM 兼容包装器 —— 当 GaussianHMM 无法收敛时的兜底方案"""
    def __init__(self, states, n_states):
        self.n_states = n_states
        self.transmat_ = np.ones((n_states, n_states)) / n_states  # 均匀转移
        self.means_ = np.zeros((n_states, 1))
        self.predict = None  # 在 _fit_simple_threshold 中赋值


# ═══════════════════════════════════════════════════════════════════════
# Markov 状态识别（Gaussian HMM）
# ═══════════════════════════════════════════════════════════════════════

class RegimeDetector:
    """使用 Gaussian HMM 识别市场状态（牛市/熊市/震荡）"""

    def __init__(self, n_states=3, random_state=42, n_iter=100):
        self.n_states = n_states
        self.random_state = random_state
        self.n_iter = n_iter
        self.model = None
        self.state_labels_ = {}   # state_idx -> "bull"/"bear"/"sideways"
        self.means_ = None

    def fit(self, returns):
        """对收益率序列拟合 HMM 模型

        Args:
            returns: 1D ndarray，对数收益率序列
        """
        try:
            from hmmlearn import hmm
        except ImportError:
            raise QuantAnalysisError("缺少 hmmlearn 库，请运行 pip install hmmlearn 安装。")

        X = returns.reshape(-1, 1) if returns.ndim == 1 else returns
        if X.shape[0] < 20:
            raise QuantAnalysisError("数据样本太少（少于 20 期），无法进行状态识别。")

        # 多次尝试拟合，使用不同初始化和协方差类型
        best_model = None
        best_states = None
        best_score = -1  # 评分：用最小状态占比衡量均衡性

        # 为每次尝试准备不同的初始均值猜测
        flat_returns = X.flatten()
        pcts = np.linspace(0, 100, self.n_states + 2)[1:-1]  # 均分点
        init_means_guesses = [
            np.percentile(flat_returns, pcts).reshape(-1, 1),  # 分位数均值
            np.array([flat_returns.min() + i * (flat_returns.max() - flat_returns.min()) / (self.n_states - 1)
                      for i in range(self.n_states)]).reshape(-1, 1),  # 均匀间隔均值
        ]

        cov_types = ["diag", "spherical", "full"]
        random_states = [42, 123, 999, 7777, 54321]

        for attempt in range(min(6, len(cov_types) * len(random_states))):
            cov_type = cov_types[attempt % len(cov_types)]
            rs = random_states[attempt % len(random_states)]
            n_iter = self.n_iter + attempt * 30

            try:
                model = hmm.GaussianHMM(
                    n_components=self.n_states,
                    covariance_type=cov_type,
                    n_iter=n_iter,
                    random_state=rs,
                    tol=1e-4,
                )

                # 用猜测的均值初始化
                guess_idx = attempt % len(init_means_guesses)
                init_means = init_means_guesses[guess_idx].copy()
                if len(init_means) == self.n_states:
                    model.means_ = init_means

                model.fit(X)
                states = model.predict(X)
                unique, counts = np.unique(states, return_counts=True)
                min_pct = counts.min() / counts.sum() if len(counts) > 0 else 0

                if min_pct > best_score:
                    best_score = min_pct
                    best_model = model
                    best_states = states

                # 如果每个状态至少占 20%，视为成功
                if min_pct >= 0.20:
                    break

            except Exception:
                continue

        # 如果所有尝试都没达到合理水平，用分位数兜底
        if best_model is None or best_score < 0.05:
            self._fit_simple_threshold(returns)
            return

        self.model = best_model
        self.means_ = self.model.means_.flatten()
        states = best_states

        # 归一化转移矩阵，避免某行为 0
        transmat = self.model.transmat_.copy()
        row_sums = transmat.sum(axis=1, keepdims=True)
        row_sums[row_sums < 1e-10] = 1.0
        transmat = transmat / row_sums
        self.model.transmat_ = transmat

        # 根据平均收益率将状态映射为标签
        sorted_idx = np.argsort(self.means_)
        if self.n_states == 2:
            self.state_labels_ = {int(sorted_idx[0]): "bear", int(sorted_idx[1]): "bull"}
        else:
            self.state_labels_ = {int(sorted_idx[0]): "bear"}
            for j in sorted_idx[1:-1]:
                self.state_labels_[int(j)] = "sideways"
            self.state_labels_[int(sorted_idx[-1])] = "bull" if len(sorted_idx) >= 3 else "bull"

    def _fit_simple_threshold(self, returns):
        """简单阈值兜底方案：当 HMM 无法收敛时，用收益率分位数划分状态"""
        returns = np.array(returns, dtype=float).flatten()
        n = len(returns)
        if self.n_states == 2:
            # 中位数分割：上半为 bull，下半为 bear
            median = np.median(returns)
            states = np.where(returns >= median, 1, 0)
            self.means_ = np.array([returns[states == 0].mean(), returns[states == 1].mean()])
            self.state_labels_ = {0: "bear", 1: "bull"}
        else:
            # 三分位数分割
            p33, p67 = np.percentile(returns, [33, 67])
            states = np.zeros(n, dtype=int)
            states[returns >= p33] = 1
            states[returns >= p67] = 2
            means = [returns[states == 0].mean(), returns[states == 1].mean(), returns[states == 2].mean()]
            self.means_ = np.array(means)
            sorted_idx = np.argsort(self.means_)
            self.state_labels_ = {int(sorted_idx[0]): "bear"}
            for j in sorted_idx[1:-1]:
                self.state_labels_[int(j)] = "sideways"
            self.state_labels_[int(sorted_idx[-1])] = "bull"

        # 伪造一个简单的 HMM 兼容接口
        self.model = _SimpleHMM(states, self.n_states)
        self.model.predict = lambda X: states[:len(X)] if len(X) <= n else np.resize(states, len(X))

    def predict_regime(self, returns):
        """预测市场状态标签

        Returns:
            list[str]: 每个时间点的状态标签
        """
        if self.model is None:
            raise QuantAnalysisError("请先调用 fit() 训练模型。")
        X = returns.reshape(-1, 1) if returns.ndim == 1 else returns
        states = self.model.predict(X)
        return [self.state_labels_.get(int(s), f"state_{s}") for s in states]

    def transition_matrix(self):
        """状态转移概率矩阵"""
        if self.model is None:
            return None
        return self.model.transmat_

    def stationary_distribution(self):
        """各状态的长期概率分布"""
        transmat = self.transition_matrix()
        if transmat is None:
            return None
        # 求解 pi * P = pi，sum(pi) = 1
        n = transmat.shape[0]
        A = np.vstack([(transmat.T - np.eye(n))[:-1], np.ones(n)])
        b = np.append(np.zeros(n - 1), 1)
        try:
            pi = np.linalg.lstsq(A, b, rcond=None)[0]
            pi = np.clip(pi, 0, None)
            return pi / pi.sum()
        except Exception:
            return np.ones(n) / n

    def state_labels_list(self):
        """按状态索引排序的标签列表"""
        return [self.state_labels_.get(i, f"state_{i}") for i in range(self.n_states)]


# ═══════════════════════════════════════════════════════════════════════
# ARIMA 时间序列预测
# ═══════════════════════════════════════════════════════════════════════

class ARIMAForecaster:
    """ARIMA 时间序列预测器"""

    def __init__(self, order=(2, 1, 2)):
        self.order = order
        self.model_fit = None
        self.aic = None
        self.bic = None

    def fit(self, series):
        """拟合 ARIMA 模型

        Args:
            series: 1D ndarray，价格序列（非收益率）
        """
        from statsmodels.tsa.arima.model import ARIMA

        if isinstance(series, list):
            series = np.array(series, dtype=float)

        if series.ndim != 1:
            raise QuantAnalysisError("价格序列必须是 1 维数组。")
        if len(series) < 30:
            raise QuantAnalysisError("数据样本太少（少于 30 期），无法拟合 ARIMA 模型。")

        try:
            self.model_fit = ARIMA(series, order=self.order).fit(method_kwargs={"maxiter": 500})
            self.aic = self.model_fit.aic
            self.bic = self.model_fit.bic
        except Exception as e:
            # 降阶重试
            try:
                self.model_fit = ARIMA(series, order=(1, 1, 1)).fit(method_kwargs={"maxiter": 500})
                self.aic = self.model_fit.aic
                self.bic = self.model_fit.bic
            except Exception:
                raise QuantAnalysisError(f"ARIMA 模型拟合失败：{e}")

    def forecast(self, steps=12):
        """预测未来 N 期价格

        Returns:
            dict: forecast（预测均值）, lower_bound, upper_bound（95% 置信区间）, aic, bic
        """
        if self.model_fit is None:
            raise QuantAnalysisError("请先调用 fit() 训练模型。")

        forecast_result = self.model_fit.get_forecast(steps=steps)
        mean = forecast_result.predicted_mean
        ci = forecast_result.conf_int()

        return {
            "steps": list(range(1, steps + 1)),
            "forecast": mean.tolist(),
            "lower_bound": ci[:, 0].tolist(),
            "upper_bound": ci[:, 1].tolist(),
            "aic": self.aic,
            "bic": self.bic,
        }

    def residuals(self):
        if self.model_fit is None:
            return None
        return self.model_fit.resid


# ═══════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════

def run_quant_analysis(
    prices,
    arima_order=(2, 1, 2),
    markov_states=3,
    forecast_steps=12,
    random_state=42,
):
    """运行完整的量化分析流程。

    Args:
        prices: 1D ndarray，价格序列
        arima_order: ARIMA (p, d, q) 阶数
        markov_states: HMM 状态数
        forecast_steps: 预测期数
        random_state: 随机种子

    Returns:
        dict:
            prices: list[float]               — 原始价格
            log_returns: list[float]          — 对数收益率
            regimes: list[str]                — 每期状态标签
            transition_matrix: list[list[float]] — 转移矩阵
            state_means: dict                 — 各状态平均收益率
            state_distribution: list[float]   — 长期状态分布
            forecast: dict                    — 预测结果
            metrics: dict                     — 汇总指标
    """
    prices = np.array(prices, dtype=float)
    if prices.ndim != 1:
        raise QuantAnalysisError("价格序列必须是 1 维数组。")
    if len(prices) < 50:
        raise QuantAnalysisError("数据太少（至少需要 50 期），建议提供更长时间的价格数据。")

    # 计算对数收益率
    log_returns = np.diff(np.log(prices))
    log_returns = log_returns[np.isfinite(log_returns)]

    if len(log_returns) < 20:
        raise QuantAnalysisError("有效收益率数据不足。")

    # ── 1. Markov 状态识别 ──
    detector = RegimeDetector(n_states=markov_states, random_state=random_state)
    detector.fit(log_returns)
    regimes = detector.predict_regime(log_returns)
    state_labels_ordered = detector.state_labels_list()

    # 各状态的平均收益率
    state_means_map = {}
    for i, label in enumerate(state_labels_ordered):
        mask = np.array([r == label for r in regimes])
        if mask.any():
            state_means_map[label] = round(float(log_returns[mask].mean()), 8)
        else:
            state_means_map[label] = 0.0

    transmat = detector.transition_matrix()
    transmat_list = transmat.tolist() if transmat is not None else []

    stationary = detector.stationary_distribution()
    stationary_list = stationary.tolist() if stationary is not None else []

    # ── 2. ARIMA 预测 ──
    forecaster = ARIMAForecaster(order=arima_order)
    forecaster.fit(prices)
    forecast_result = forecaster.forecast(steps=forecast_steps)

    # ── 3. 汇总指标 ──
    total_return = float(prices[-1] / prices[0] - 1) if prices[0] > 0 else 0
    ann_return = total_return * (52 / len(prices)) if len(prices) > 0 else 0
    ann_vol = float(np.std(log_returns) * np.sqrt(52)) if len(log_returns) > 0 else 0
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    return {
        "prices": prices.tolist(),
        "log_returns": log_returns.tolist(),
        "regimes": regimes,
        "state_labels": state_labels_ordered,
        "transition_matrix": transmat_list,
        "state_means": state_means_map,
        "state_distribution": {label: round(float(p), 6) for label, p in zip(state_labels_ordered, stationary_list)}
        if len(state_labels_ordered) == len(stationary_list) else {},
        "forecast": forecast_result,
        "metrics": {
            "total_return": round(total_return, 6),
            "annualized_return": round(ann_return, 6),
            "annualized_volatility": round(ann_vol, 6),
            "sharpe_ratio": round(sharpe, 4),
            "n_periods": len(prices),
        },
    }
