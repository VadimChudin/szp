//+------------------------------------------------------------------+
//|                                       SmartZonesCollector.mq5    |
//|                                          Smart Zones Pro v2.0    |
//|                                                                  |
//| EA для сбора тиковых данных и экспорта OHLCV свечей (MT5).       |
//| Запускается на графике XAUUSD (или любом другом символе).        |
//|                                                                  |
//| Функции:                                                         |
//|   1. OnTick() — запись каждого тика (Bid/Ask/Direction)          |
//|   2. OnTimer() — экспорт OHLCV свечей H1/H4/D1                  |
//|   3. Кнопка FP — запрос на открытие окна футпринта               |
//|   4. Статус-панель на графике                                    |
//|                                                                  |
//| Файлы записываются в Common/Files/ (FILE_COMMON):                |
//|   - smartzones_ticks_{Sym}.csv    (тиковый поток реального времени)
//|   - {Symbol}_H1.csv               (часовые свечи)                |
//|   - {Symbol}_H4.csv               (4-часовые свечи)              |
//|   - {Symbol}_D1.csv               (дневные свечи)                |
//+------------------------------------------------------------------+
#property copyright "Smart Zones Pro"
#property link      ""
#property version   "2.00"

//--- Input Parameters ------------------------------------------------
input int      TickBufferMaxLines  = 200000;   // Макс. тиков в буфере (~несколько дней)
input int      OHLCVRefreshSec     = 30;       // Интервал обновления OHLCV (сек)
input int      H1_Bars             = 200;      // Баров H1 для экспорта
input int      H4_Bars             = 100;      // Баров H4 для экспорта
input int      D1_Bars             = 60;       // Баров D1 для экспорта
input int      M1_Bars             = 15000;    // Баров M1 для эмуляции истории (~10 дней)
input color    PanelTextColor      = clrWhite; // Цвет текста панели
input color    PanelBgColor        = C'30,30,40'; // Фон панели

//--- Глобальные переменные -------------------------------------------
string   g_prefix     = "SZC_";           // Префикс объектов
double   g_prevBid    = 0;                // Предыдущий Bid
double   g_prevAsk    = 0;                // Предыдущий Ask
int      g_tickCount  = 0;                // Счётчик тиков текущей сессии
int      g_tickFileHandle = INVALID_HANDLE;
datetime g_lastOHLCV  = 0;                // Время последнего экспорта OHLCV
string   g_tickFileName = "";             // Имя файла тиков
string   g_symbolName = "";               // Имя символа (для файлов)


//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   g_symbolName = Symbol();

   g_prevBid = SymbolInfoDouble(g_symbolName, SYMBOL_BID);
   g_prevAsk = SymbolInfoDouble(g_symbolName, SYMBOL_ASK);

   g_tickFileName = "smartzones_ticks_" + g_symbolName + ".csv";
   g_tickFileHandle = FileOpen(
      g_tickFileName,
      FILE_WRITE|FILE_READ|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE,
      ','
   );

   if(g_tickFileHandle == INVALID_HANDLE)
   {
      Print("[Collector] ERROR: Cannot create tick file: ", g_tickFileName,
            " Error: ", GetLastError());
      return(INIT_FAILED);
   }

   FileWrite(g_tickFileHandle,
      "# broker=" + AccountInfoString(ACCOUNT_COMPANY) +
      ", symbol=" + Symbol() +
      ", server=" + AccountInfoString(ACCOUNT_SERVER) +
      ", digits=" + IntegerToString(_Digits) +
      ", point=" + DoubleToString(_Point, 8));
   FileWrite(g_tickFileHandle, "timestamp_ms", "bid", "ask", "direction");
   FileFlush(g_tickFileHandle);

   EventSetTimer(OHLCVRefreshSec);

   ExportAllOHLCV();
   CreateFPButton();
   CreateStatusPanel();
   UpdateStatusPanel("Initializing...", 0);

   Print("[Collector] Started on ", Symbol(),
         " | Broker: ", AccountInfoString(ACCOUNT_COMPANY),
         " | Server: ", AccountInfoString(ACCOUNT_SERVER));
   Print("[Collector] Tick file: Common/Files/", g_tickFileName);

   return(INIT_SUCCEEDED);
}


//+------------------------------------------------------------------+
//| Expert deinitialization                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_tickFileHandle != INVALID_HANDLE)
   {
      FileClose(g_tickFileHandle);
      g_tickFileHandle = INVALID_HANDLE;
   }

   ObjectsDeleteAll(0, g_prefix);
   EventKillTimer();
   Print("[Collector] Stopped. Total ticks collected: ", g_tickCount);
}


//+------------------------------------------------------------------+
//| Expert tick function — ГЛАВНАЯ: запись каждого тика               |
//+------------------------------------------------------------------+
void OnTick()
{
   if(g_tickFileHandle == INVALID_HANDLE)
      return;

   double curBid = SymbolInfoDouble(g_symbolName, SYMBOL_BID);
   double curAsk = SymbolInfoDouble(g_symbolName, SYMBOL_ASK);

   // ── Классификация тика (Quote Rule) ──────────────────────────
   string direction = "NEUTRAL";

   if(curBid > g_prevBid)
      direction = "BUY";
   else if(curBid < g_prevBid)
      direction = "SELL";
   else
   {
      if(curAsk > g_prevAsk)
         direction = "BUY";
      else if(curAsk < g_prevAsk)
         direction = "SELL";
   }

   long timestamp_ms = (long)TimeCurrent() * 1000 + GetTickCount() % 1000;

   FileWrite(g_tickFileHandle,
      IntegerToString(timestamp_ms),
      DoubleToString(curBid, _Digits),
      DoubleToString(curAsk, _Digits),
      direction
   );

   g_tickCount++;

   if(g_tickCount % 10 == 0)
      FileFlush(g_tickFileHandle);

   if(g_tickCount >= TickBufferMaxLines)
      RotateTickFile();

   g_prevBid = curBid;
   g_prevAsk = curAsk;

   if(g_tickCount % 500 == 0)
      UpdateStatusPanel(direction, g_tickCount);
}


//+------------------------------------------------------------------+
//| Timer — периодический экспорт OHLCV свечей                       |
//+------------------------------------------------------------------+
void OnTimer()
{
   ExportAllOHLCV();
   UpdateStatusPanel("", g_tickCount);
}


//+------------------------------------------------------------------+
//| Chart events — кнопка FP                                          |
//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   if(id == CHARTEVENT_OBJECT_CLICK)
   {
      if(sparam == g_prefix + "FP_BTN")
      {
         ObjectSetInteger(0, g_prefix + "FP_BTN", OBJPROP_STATE, false);

         string fpInterval = "4h";
         ENUM_TIMEFRAMES per = (ENUM_TIMEFRAMES)Period();
         if(per <= PERIOD_H1) fpInterval = "1h";
         else if(per <= PERIOD_H4) fpInterval = "4h";
         else fpInterval = "1d";

         int fh = FileOpen("footprint_request.flag",
                           FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ);
         if(fh != INVALID_HANDLE)
         {
            FileWriteString(fh, fpInterval);
            FileClose(fh);
            Print("[Collector] Footprint requested: ", fpInterval);
         }

         int fh2 = FileOpen("new_data.flag",
                            FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ);
         if(fh2 != INVALID_HANDLE)
         {
            FileWriteString(fh2, "recalc");
            FileClose(fh2);
         }

         ChartRedraw();
      }
   }
}


//+------------------------------------------------------------------+
//| Экспорт OHLCV для всех таймфреймов                               |
//+------------------------------------------------------------------+
void ExportAllOHLCV()
{
   ExportOHLCV(PERIOD_M1, "M1", M1_Bars);
   ExportOHLCV(PERIOD_H1, "H1", H1_Bars);
   ExportOHLCV(PERIOD_H4, "H4", H4_Bars);
   ExportOHLCV(PERIOD_D1, "D1", D1_Bars);

   g_lastOHLCV = TimeCurrent();

   int fh = FileOpen("ohlcv_updated.flag",
                     FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ);
   if(fh != INVALID_HANDLE)
   {
      FileWriteString(fh, TimeToString(TimeCurrent()));
      FileClose(fh);
   }
}


//+------------------------------------------------------------------+
//| Экспорт OHLCV одного таймфрейма в CSV                            |
//+------------------------------------------------------------------+
void ExportOHLCV(ENUM_TIMEFRAMES timeframe, string tf_label, int bars)
{
   string filename = g_symbolName + "_" + tf_label + ".csv";

   int fh = FileOpen(filename,
                     FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE,
                     ',');
   if(fh == INVALID_HANDLE)
   {
      Print("[Collector] ERROR: Cannot write ", filename, " Error: ", GetLastError());
      return;
   }

   FileWrite(fh,
      "# broker=" + AccountInfoString(ACCOUNT_COMPANY) +
      ", symbol=" + Symbol() +
      ", server=" + AccountInfoString(ACCOUNT_SERVER));
   FileWrite(fh, "time", "open", "high", "low", "close", "tick_volume");

   int totalBars = Bars(Symbol(), timeframe);
   int available = MathMin(bars, totalBars - 1);
   if(available < 1)
   {
      FileClose(fh);
      return;
   }

   datetime times[];
   double   opens[], highs[], lows[], closes[];
   long     tickVols[];

   int needed = available + 1;
   if(CopyTime(Symbol(),       timeframe, 0, needed, times)   <= 0 ||
      CopyOpen(Symbol(),       timeframe, 0, needed, opens)   <= 0 ||
      CopyHigh(Symbol(),       timeframe, 0, needed, highs)   <= 0 ||
      CopyLow(Symbol(),        timeframe, 0, needed, lows)    <= 0 ||
      CopyClose(Symbol(),      timeframe, 0, needed, closes)  <= 0 ||
      CopyTickVolume(Symbol(), timeframe, 0, needed, tickVols) <= 0)
   {
      Print("[Collector] ERROR copying ", tf_label, " bars: ", GetLastError());
      FileClose(fh);
      return;
   }

   // CopyXxx returns ascending order (oldest first), so just iterate directly.
   for(int i = 0; i < needed; i++)
   {
      FileWrite(fh,
         TimeToString(times[i], TIME_DATE|TIME_MINUTES),
         DoubleToString(opens[i],  _Digits),
         DoubleToString(highs[i],  _Digits),
         DoubleToString(lows[i],   _Digits),
         DoubleToString(closes[i], _Digits),
         IntegerToString(tickVols[i])
      );
   }

   FileClose(fh);
}


//+------------------------------------------------------------------+
//| Ротация файла тиков (перезапись при переполнении)                 |
//+------------------------------------------------------------------+
void RotateTickFile()
{
   if(g_tickFileHandle != INVALID_HANDLE)
      FileClose(g_tickFileHandle);

   string oldName = "smartzones_ticks_" + g_symbolName + "_old.csv";
   FileDelete(oldName, FILE_COMMON);

   g_tickFileHandle = FileOpen(
      g_tickFileName,
      FILE_WRITE|FILE_READ|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE,
      ','
   );

   if(g_tickFileHandle != INVALID_HANDLE)
   {
      FileWrite(g_tickFileHandle,
         "# broker=" + AccountInfoString(ACCOUNT_COMPANY) +
         ", symbol=" + Symbol() +
         ", server=" + AccountInfoString(ACCOUNT_SERVER) +
         ", digits=" + IntegerToString(_Digits) +
         ", point=" + DoubleToString(_Point, 8));
      FileWrite(g_tickFileHandle, "timestamp_ms", "bid", "ask", "direction");
      FileFlush(g_tickFileHandle);
   }

   g_tickCount = 0;
   Print("[Collector] Tick file rotated. Starting fresh buffer.");
}


//+------------------------------------------------------------------+
//| Создание кнопки FP на графике                                    |
//+------------------------------------------------------------------+
void CreateFPButton()
{
   string name = g_prefix + "FP_BTN";
   ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 50);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, 55);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, 28);
   ObjectSetString(0, name, OBJPROP_TEXT, " FP ");
   ObjectSetString(0, name, OBJPROP_FONT, "Arial Bold");
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, C'40,80,160');
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, C'60,100,200');
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
}


//+------------------------------------------------------------------+
//| Создание статус-панели                                            |
//+------------------------------------------------------------------+
void CreateStatusPanel()
{
   // Фон панели
   string bgName = g_prefix + "PANEL_BG";
   ObjectCreate(0, bgName, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, bgName, OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, bgName, OBJPROP_YDISTANCE, 85);
   ObjectSetInteger(0, bgName, OBJPROP_XSIZE, 260);
   ObjectSetInteger(0, bgName, OBJPROP_YSIZE, 55);
   ObjectSetInteger(0, bgName, OBJPROP_BGCOLOR, PanelBgColor);
   ObjectSetInteger(0, bgName, OBJPROP_BORDER_COLOR, C'60,60,80');
   ObjectSetInteger(0, bgName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, bgName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, bgName, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, bgName, OBJPROP_BACK, false);

   string line1 = g_prefix + "STATUS_1";
   ObjectCreate(0, line1, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, line1, OBJPROP_XDISTANCE, 18);
   ObjectSetInteger(0, line1, OBJPROP_YDISTANCE, 92);
   ObjectSetString(0, line1, OBJPROP_TEXT, "Collector: starting...");
   ObjectSetString(0, line1, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, line1, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, line1, OBJPROP_COLOR, PanelTextColor);
   ObjectSetInteger(0, line1, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, line1, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, line1, OBJPROP_HIDDEN, true);

   string line2 = g_prefix + "STATUS_2";
   ObjectCreate(0, line2, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, line2, OBJPROP_XDISTANCE, 18);
   ObjectSetInteger(0, line2, OBJPROP_YDISTANCE, 112);
   ObjectSetString(0, line2, OBJPROP_TEXT,
                   Symbol() + " | " + AccountInfoString(ACCOUNT_COMPANY));
   ObjectSetString(0, line2, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, line2, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, line2, OBJPROP_COLOR, C'140,140,160');
   ObjectSetInteger(0, line2, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, line2, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, line2, OBJPROP_HIDDEN, true);
}


//+------------------------------------------------------------------+
//| Обновление статус-панели                                         |
//+------------------------------------------------------------------+
void UpdateStatusPanel(string lastDir, int ticks)
{
   string dirSymbol = "*";
   color  dirColor  = C'140,140,160';

   if(lastDir == "BUY")       { dirSymbol = "^"; dirColor = clrLime; }
   else if(lastDir == "SELL") { dirSymbol = "v"; dirColor = clrRed; }

   double bid = SymbolInfoDouble(Symbol(), SYMBOL_BID);
   string line1Text = StringFormat("Ticks: %d | %s %.2f | LIVE",
                                    ticks, dirSymbol, bid);

   ObjectSetString(0, g_prefix + "STATUS_1", OBJPROP_TEXT, line1Text);
   ObjectSetInteger(0, g_prefix + "STATUS_1", OBJPROP_COLOR, dirColor);
}
//+------------------------------------------------------------------+
