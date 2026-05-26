//+------------------------------------------------------------------+
//|                                       SmartZonesCollector.mq4    |
//|                                          Smart Zones Pro v2.0    |
//|                                                                  |
//| EA для сбора тиковых данных и экспорта OHLCV свечей.             |
//| Запускается на графике XAUUSD (или любом другом символе).        |
//|                                                                  |
//| Функции:                                                         |
//|   1. OnTick() — запись каждого тика (Bid/Ask/Direction)          |
//|   2. OnTimer() — экспорт OHLCV свечей H1/H4/D1                  |
//|   3. Кнопка FP — запрос на открытие окна футпринта               |
//|   4. Статус-панель на графике                                    |
//|                                                                  |
//| Файлы записываются в Common/Files/ (FILE_COMMON):                |
//|   - tick_buffer.csv    (тиковый поток реального времени)          |
//|   - {Symbol}_H1.csv    (часовые свечи)                           |
//|   - {Symbol}_H4.csv    (4-часовые свечи)                         |
//|   - {Symbol}_D1.csv    (дневные свечи)                           |
//+------------------------------------------------------------------+
#property copyright "Smart Zones Pro"
#property link      ""
#property version   "2.00"
#property strict

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
double   g_prevBid    = 0;                // Предыдущий Bid (для определения направления)
double   g_prevAsk    = 0;                // Предыдущий Ask
int      g_tickCount  = 0;                // Счетчик тиков текущей сессии
int      g_tickFileHandle = INVALID_HANDLE; // Хендл файла тиков
datetime g_lastOHLCV  = 0;                // Время последнего экспорта OHLCV
string   g_tickFileName = "";             // Имя файла тиков
string   g_symbolName = "";               // Имя символа (для файлов)

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   // Сохраняем имя символа (убираем точки и спец.символы для имени файла)
   g_symbolName = Symbol();
   
   // Инициализируем предыдущие цены
   g_prevBid = Bid;
   g_prevAsk = Ask;
   
   // ── Открываем файл тиков ──────────────────────────────────────
   g_tickFileName = "smartzones_ticks_" + g_symbolName + ".csv";
   g_tickFileHandle = FileOpen(g_tickFileName, FILE_WRITE|FILE_READ|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, ',');
   
   if(g_tickFileHandle == INVALID_HANDLE)
   {
      Print("[Collector] ERROR: Cannot create tick file: ", g_tickFileName, " Error: ", GetLastError());
      return(INIT_FAILED);
   }
   
   // Записываем заголовок с метаданными
   FileWrite(g_tickFileHandle, "# broker=" + AccountCompany() + 
             ", symbol=" + Symbol() + 
             ", server=" + AccountServer() +
             ", digits=" + IntegerToString(Digits) +
             ", point=" + DoubleToString(Point, 8));
   FileWrite(g_tickFileHandle, "timestamp_ms", "bid", "ask", "direction");
   FileFlush(g_tickFileHandle);
   
   // ── Таймер для OHLCV ─────────────────────────────────────────
   EventSetTimer(OHLCVRefreshSec);
   
   // Первый экспорт OHLCV сразу
   ExportAllOHLCV();
   
   // ── Кнопка FP ────────────────────────────────────────────────
   CreateFPButton();
   
   // ── Статус-панель ─────────────────────────────────────────────
   CreateStatusPanel();
   UpdateStatusPanel("Initializing...", 0);
   
   Print("[Collector] Started on ", Symbol(), " | Broker: ", AccountCompany(), 
         " | Server: ", AccountServer());
   Print("[Collector] Tick file: Common/Files/", g_tickFileName);
   
   return(INIT_SUCCEEDED);
}


//+------------------------------------------------------------------+
//| Expert deinitialization                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // Закрываем файл тиков
   if(g_tickFileHandle != INVALID_HANDLE)
   {
      FileClose(g_tickFileHandle);
      g_tickFileHandle = INVALID_HANDLE;
   }
   
   // Удаляем объекты
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
   
   double curBid = Bid;
   double curAsk = Ask;
   
   // ── Классификация тика (Quote Rule) ──────────────────────────
   // Если Bid вырос → кто-то агрессивно купил (ударил по аску)
   // Если Bid упал  → кто-то агрессивно продал (ударил по биду)
   string direction = "NEUTRAL";
   
   if(curBid > g_prevBid)
      direction = "BUY";
   else if(curBid < g_prevBid)
      direction = "SELL";
   else
   {
      // Bid не изменился — смотрим на Ask
      if(curAsk > g_prevAsk)
         direction = "BUY";
      else if(curAsk < g_prevAsk)
         direction = "SELL";
   }
   
   // ── Записываем тик ───────────────────────────────────────────
   long timestamp_ms = (long)TimeCurrent() * 1000 + GetTickCount() % 1000;
   
   FileWrite(g_tickFileHandle,
      IntegerToString(timestamp_ms),
      DoubleToString(curBid, Digits),
      DoubleToString(curAsk, Digits),
      direction
   );
   
   g_tickCount++;
   
   // Flush каждые 10 тиков для быстрого отображения в реальном времени
   if(g_tickCount % 10 == 0)
      FileFlush(g_tickFileHandle);
   
   // ── Ротация файла (если превышен лимит) ──────────────────────
   if(g_tickCount >= TickBufferMaxLines)
   {
      RotateTickFile();
   }
   
   // Обновляем предыдущие значения
   g_prevBid = curBid;
   g_prevAsk = curAsk;
   
   // Обновляем статус на экране каждые 500 тиков
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
         // Отжимаем кнопку
         ObjectSetInteger(0, g_prefix + "FP_BTN", OBJPROP_STATE, false);
         
         // Определяем таймфрейм
         string fpInterval = "4h";
         int per = Period();
         if(per <= PERIOD_H1) fpInterval = "1h";
         else if(per <= PERIOD_H4) fpInterval = "4h";
         else fpInterval = "1d";
         
         // Пишем флаг для Python
         int fh = FileOpen("footprint_request.flag", FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ);
         if(fh != INVALID_HANDLE)
         {
            FileWriteString(fh, fpInterval);
            FileClose(fh);
            Print("[Collector] Footprint requested: ", fpInterval);
         }
         
         // Пишем флаг на пересчёт зон
         int fh2 = FileOpen("new_data.flag", FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ);
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
   
   // Создаём флаг для Python что данные обновлены
   int fh = FileOpen("ohlcv_updated.flag", FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ);
   if(fh != INVALID_HANDLE)
   {
      FileWriteString(fh, TimeToString(TimeCurrent()));
      FileClose(fh);
   }
}


//+------------------------------------------------------------------+
//| Экспорт OHLCV одного таймфрейма в CSV                            |
//+------------------------------------------------------------------+
void ExportOHLCV(int timeframe, string tf_label, int bars)
{
   string filename = g_symbolName + "_" + tf_label + ".csv";
   
   int fh = FileOpen(filename, FILE_WRITE|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, ',');
   if(fh == INVALID_HANDLE)
   {
      Print("[Collector] ERROR: Cannot write ", filename, " Error: ", GetLastError());
      return;
   }
   
   // Заголовок с метаданными брокера
   FileWrite(fh, "# broker=" + AccountCompany() + 
             ", symbol=" + Symbol() + 
             ", server=" + AccountServer());
   FileWrite(fh, "time", "open", "high", "low", "close", "tick_volume");
   
   // Данные (от старых к новым)
   int available = MathMin(bars, iBars(Symbol(), timeframe) - 1);
   
   for(int i = available; i >= 0; i--)  // Включаем i=0 (текущую живую свечу!)
   {
      datetime t = iTime(Symbol(), timeframe, i);
      double   o = iOpen(Symbol(), timeframe, i);
      double   h = iHigh(Symbol(), timeframe, i);
      double   l = iLow(Symbol(), timeframe, i);
      double   c = iClose(Symbol(), timeframe, i);
      long     v = iVolume(Symbol(), timeframe, i);
      
      FileWrite(fh,
         TimeToString(t, TIME_DATE|TIME_MINUTES),
         DoubleToString(o, Digits),
         DoubleToString(h, Digits),
         DoubleToString(l, Digits),
         DoubleToString(c, Digits),
         IntegerToString(v)
      );
   }
   
   FileClose(fh);
}


//+------------------------------------------------------------------+
//| Ротация файла тиков (перезапись при переполнении)                 |
//+------------------------------------------------------------------+
void RotateTickFile()
{
   // Закрываем текущий файл
   if(g_tickFileHandle != INVALID_HANDLE)
      FileClose(g_tickFileHandle);
   
   // Переименовываем текущий в .old (для бэкапа)
   string oldName = "smartzones_ticks_" + g_symbolName + "_old.csv";
   FileDelete(oldName, FILE_COMMON);
   
   // Открываем новый файл
   g_tickFileHandle = FileOpen(g_tickFileName, FILE_WRITE|FILE_READ|FILE_CSV|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, ',');
   
   if(g_tickFileHandle != INVALID_HANDLE)
   {
      FileWrite(g_tickFileHandle, "# broker=" + AccountCompany() + 
                ", symbol=" + Symbol() + 
                ", server=" + AccountServer() +
                ", digits=" + IntegerToString(Digits) +
                ", point=" + DoubleToString(Point, 8));
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
   
   // Строка 1: Тиковый статус
   string line1 = g_prefix + "STATUS_1";
   ObjectCreate(0, line1, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, line1, OBJPROP_XDISTANCE, 18);
   ObjectSetInteger(0, line1, OBJPROP_YDISTANCE, 92);
   ObjectSetString(0, line1, OBJPROP_TEXT, "⚡ Collector: starting...");
   ObjectSetString(0, line1, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, line1, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, line1, OBJPROP_COLOR, PanelTextColor);
   ObjectSetInteger(0, line1, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, line1, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, line1, OBJPROP_HIDDEN, true);
   
   // Строка 2: Брокер
   string line2 = g_prefix + "STATUS_2";
   ObjectCreate(0, line2, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, line2, OBJPROP_XDISTANCE, 18);
   ObjectSetInteger(0, line2, OBJPROP_YDISTANCE, 112);
   ObjectSetString(0, line2, OBJPROP_TEXT, Symbol() + " | " + AccountCompany());
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
   string dirSymbol = "●";
   color dirColor = C'140,140,160';
   
   if(lastDir == "BUY") { dirSymbol = "▲"; dirColor = clrLime; }
   else if(lastDir == "SELL") { dirSymbol = "▼"; dirColor = clrRed; }
   
   string line1Text = StringFormat("⚡ Ticks: %d | %s %.2f | LIVE", 
                                    ticks, dirSymbol, Bid);
   
   ObjectSetString(0, g_prefix + "STATUS_1", OBJPROP_TEXT, line1Text);
   ObjectSetInteger(0, g_prefix + "STATUS_1", OBJPROP_COLOR, dirColor);
}
//+------------------------------------------------------------------+
