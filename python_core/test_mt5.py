import MetaTrader5 as mt5

print("Initializing MT5 to active session (auto-discovery)...")

# If we omit EVERYTHING, the API finds the actively running MT5 window by its window handle!
if mt5.initialize():
    print("Initialize successful!")
    print(mt5.terminal_info())
    print("Active Account:", mt5.account_info())
else:
    print("Initialize failed entirely. Error:", mt5.last_error())

mt5.shutdown()

mt5.shutdown()

mt5.shutdown()

mt5.shutdown()
