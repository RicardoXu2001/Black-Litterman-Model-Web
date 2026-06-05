from structures import *
from black_litterman import BlackLitterman
from back_test import BackTest


if __name__ == "__main__":

    print("-" * 30, 'Initial Black Litterman Model', "-" * 30)
    type_name = VIEW_TYPE_NAME[VIEW_TYPE]
    print('Use view type: ', type_name)
    bl = BlackLitterman()
    bl.get_cc_return()
    bl.get_market_value_weight()

    print("-" * 30, 'Do Back Test', "-" * 30)
    bt = BackTest()
    summary = bt.back_test(bl)

    print("-" * 30, 'Back Test Summary', "-" * 30)
    print("Gross accumulated log return:", round(summary["gross_accumulated_log_return"], 6))
    print("Net accumulated log return:", round(summary["net_accumulated_log_return"], 6))
    print("Equal weight accumulated log return:", round(summary["equal_weight_accumulated_log_return"], 6))
    print("Average turnover:", round(summary["average_turnover"], 6))
    print("Total transaction cost:", round(summary["total_transaction_cost"], 6))
    print("Plot saved to:", PLOT_DIR)
    print("Detailed result saved to:", RESULT_DIR)
