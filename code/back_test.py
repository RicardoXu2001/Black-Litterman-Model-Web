import pandas as pd
import numpy as np
import os
from structures import *

os.environ.setdefault("MPLCONFIGDIR", os.path.join(BASE_DIR, ".matplotlib"))
import matplotlib.pyplot as plt

class BackTest:
    def __init__(self):
        self.start_index = START_INDEX
        self.end_index = END_INDEX
        self.transaction_cost_bps = TRANSACTION_COST_BPS
        self.plot_dir = PLOT_DIR
        self.result_dir = RESULT_DIR

    def back_test(self, bl):
        start_index = self.start_index
        end_index = self.end_index
        gross_ret_port_set = []
        net_ret_port_set = []
        weight_port_set = []
        turnover_set = []
        cost_set = []
        previous_weight = None

        for cur_idx in range(start_index, end_index + 1):
            weight_bl, real_ret = bl.get_post_weight(cur_idx, previous_weight)
            gross_ret = np.dot(weight_bl, real_ret.T)
            turnover = 0.0 if previous_weight is None else np.sum(np.abs(weight_bl - previous_weight))
            transaction_cost = turnover * self.transaction_cost_bps / 10000
            net_ret = gross_ret - transaction_cost
            gross_ret_port_set.append(gross_ret)
            net_ret_port_set.append(net_ret)
            weight_port_set.append(weight_bl)
            turnover_set.append(turnover)
            cost_set.append(transaction_cost)
            previous_weight = weight_bl

        # 计算收益率的累加列表（这里的收益率是log计算的，所以加和就代表累计收益率）
        gross_acc_ret_port_set = self.get_accumulate_return(gross_ret_port_set)
        net_acc_ret_port_set = self.get_accumulate_return(net_ret_port_set)
        eq_acc = bl.calculate_comparative_return(start_index, end_index)

        self.save_results(bl, weight_port_set, gross_ret_port_set, net_ret_port_set, turnover_set, cost_set)
        self.plot_return(gross_acc_ret_port_set, net_acc_ret_port_set, eq_acc)
        return {
            "gross_accumulated_log_return": gross_acc_ret_port_set[-1],
            "net_accumulated_log_return": net_acc_ret_port_set[-1],
            "equal_weight_accumulated_log_return": eq_acc[-1],
            "average_turnover": float(np.mean(turnover_set)),
            "total_transaction_cost": float(np.sum(cost_set))
        }

    def get_accumulate_return(self, ret_port_set):
        # Get accumulated log return all over time
        acc_ret_port_set = [0]
        for ret in ret_port_set:
            acc_ret_port_set.append(acc_ret_port_set[-1] + ret)

        return acc_ret_port_set

    def save_results(self, bl, weight_port_set, gross_ret_set, net_ret_set, turnover_set, cost_set):
        os.makedirs(self.result_dir, exist_ok=True)
        type_name = VIEW_TYPE_NAME[VIEW_TYPE]
        weight_df = pd.DataFrame(weight_port_set, columns=bl.stock_names)
        weight_df["turnover"] = turnover_set
        weight_df["transaction_cost"] = cost_set
        weight_df["gross_log_return"] = gross_ret_set
        weight_df["net_log_return"] = net_ret_set
        output_file = os.path.join(self.result_dir, "weights_and_returns_realistic_" + str(type_name) + "_" + BACK_TEST_PERIOD_NAME + ".csv")
        weight_df.to_csv(output_file, index=False)

    def plot_return(self, gross_acc_ret_port_set, net_acc_ret_port_set, eq_acc):
        os.makedirs(self.plot_dir, exist_ok=True)
        x = np.arange(0, len(net_acc_ret_port_set), 1)
        type_name = VIEW_TYPE_NAME[VIEW_TYPE]
        plt.figure(figsize=(10, 6))
        plt.plot(x, eq_acc[:len(x)], color='blue', label='Equal weight')
        plt.plot(x, gross_acc_ret_port_set, color='orange', linestyle='--', label=str(type_name) + ' gross')
        plt.plot(x, net_acc_ret_port_set, color='red', label=str(type_name) + ' net')
        plt.title('BL Return Back Test_'+str(type_name)+'_Year '+ BACK_TEST_PERIOD_NAME)
        plt.xlabel(BACK_TEST_X_LABEL)
        plt.ylabel(BACK_TEST_Y_LABEL)
        plt.legend()
        plt.tight_layout()
        filename = 'BL Return Back Test_Realistic_'+str(type_name)+'_Year '+ BACK_TEST_PERIOD_NAME + ".png"
        plt.savefig(os.path.join(self.plot_dir, filename))
        plt.close()
