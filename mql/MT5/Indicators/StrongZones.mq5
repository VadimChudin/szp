//+------------------------------------------------------------------+
//|                                              StrongZones.mq5     |
//|                                          Smart Zones Pro v1.0    |
//|                                                                  |
//| Индикатор сильных зон для XAU/USD (MetaTrader 5)                 |
//| Читает зоны из JSON-файла, сгенерированного Python Core,        |
//| и отрисовывает их на графике в виде красных линий/прямоугольников|
//+------------------------------------------------------------------+
#property copyright "Smart Zones Pro"
#property link      ""
#property version   "1.00"
#property indicator_chart_window

// Номер сборки подставляет CI при компиляции: без него нельзя было понять,
// какая версия индикатора реально загружена в терминале клиента.
#define SZP_BUILD "dev"

//--- Настройки (Input Parameters) ------------------------------------
input string   ZonesFilePath    = "zones_output.json";   // Имя файла с зонами (в Common/Files)
input int      RefreshSeconds   = 10;         // Интервал обновления (сек)
input color    ZoneColorStrong  = clrGold;        // Цвет сильных зон (Score >= 11)
input color    ZoneColorMedium  = C'200,170,60';  // Цвет средних зон
input color    ZoneColorWeak    = C'120,110,80';  // Цвет слабых зон
input int      ZoneLineWidth    = 2;          // Толщина линии
// Параметр переименован из ShowLabels: терминал хранит значения инпутов в
// профиле графика, и у клиентов оставался ShowLabels=false из старой сборки —
// цены на уровнях не появлялись даже после обновления индикатора.
input bool     ShowPriceLabels  = true;       // Показывать только цену зоны
input bool     ShowRectangles   = false;       // Полупрозрачные прямоугольники зон
input bool     ShowScoreBadge   = false;      // Бейдж со скором
input bool     ShowGradient     = false;      // Градиентная визуализация (выкл. по умолчанию)
input int      GradientLayers   = 5;          // Кол-во слоёв градиента
input bool     EnableAlerts     = true;       // Алерты при касании зоны
input double   AlertDistance    = 5.0;        // Расстояние для алерта ($)
input bool     ShowAccumulation = true;      // Набор позиции крупным участником
input string   AccumFilePath    = "accumulation_output.json"; // Файл участков набора
input color    AccumColor       = C'85,45,140';  // Цвет участков набора (фиолетовый)

//--- Глобальные переменные -------------------------------------------
string         zonePrefix       = "SZP_";
string         accumPrefix      = "SZP_ACC_";
string         buildPrefix      = "SZP_VER_";
int            currentZoneCount = 0;
int            accumCount       = 0;
int            accumReported    = -1;
datetime       zonesCalcTime    = 0;
datetime       lastAlertTime    = 0;

double         zonePrices[];
double         zoneTops[];
double         zoneBottoms[];
int            zoneScores[];
string         zoneLabels[];
bool           zoneBigPlayer[];


//+------------------------------------------------------------------+
//| Время вида "2026-06-17T22:25:31.123456" → datetime.               |
//+------------------------------------------------------------------+
datetime ParseIsoTime(string iso)
{
   if(StringLen(iso) < 19) return 0;
   string s = StringSubstr(iso, 0, 19);
   StringReplace(s, "T", " ");
   return StringToTime(s);
}

//+------------------------------------------------------------------+
//| Метка в углу графика: версия сборки, число зон/участков и  |
//| возраст данных. Старый JSON подсвечивается красным: именно   |
//| так выглядит "зоны те же" — приложение больше не считает.  |
//+------------------------------------------------------------------+
void DrawBuildStamp()
{
   string text = "SZP v" + SZP_BUILD;
   color  clr  = C'110,110,110';

   if(zonesCalcTime > 0)
   {
      int ageMin = (int)((TimeLocal() - zonesCalcTime) / 60);
      string age = ageMin < 60 ? IntegerToString(ageMin) + "m"
                              : IntegerToString(ageMin / 60) + "h";
      text += "  |  zones: " + IntegerToString(currentZoneCount) +
              "  acc: " + IntegerToString(accumCount) +
              "  " + age + " ago";
      if(ageMin > 360) clr = clrTomato;
   }
   else
      text += "  |  no zones file";

   string name = buildPrefix + "STAMP";
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_RIGHT_LOWER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 8);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 6);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_RIGHT_LOWER);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 7);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

//+------------------------------------------------------------------+
int OnInit()
{
   // Чистим объекты сразу при инициализации (в т.ч. при смене ТФ). Иначе
   // подписи/объекты, сохранённые в профиле графика от прежней версии
   // индикатора, «мигают» до первой успешной загрузки JSON.
   DeleteAllZoneObjects();
   DeleteAccumulationObjects();
   EventSetTimer(RefreshSeconds);
   LoadZonesFromFile();
   LoadAccumulationFromFile();
   DrawBuildStamp();
   Print("[SmartZones MT5] Initialized, build v", SZP_BUILD,
         ". File: ", ZonesFilePath);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   DeleteAllZoneObjects();
   DeleteAccumulationObjects();
   ObjectDelete(0, buildPrefix + "STAMP");
   EventKillTimer();
}

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(EnableAlerts && currentZoneCount > 0)
      CheckAlerts();
   return(rates_total);
}

//+------------------------------------------------------------------+
void OnTimer()
{
   LoadZonesFromFile();
   LoadAccumulationFromFile();
}

//+------------------------------------------------------------------+
//| Читает файл из Common/Files, иначе из локальной папки Files       |
//+------------------------------------------------------------------+
string ReadDataFile(string fileName)
{
   int handle = FileOpen(fileName, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      handle = FileOpen(fileName, FILE_READ|FILE_TXT|FILE_ANSI);
      if(handle == INVALID_HANDLE) return "";
   }

   string content = "";
   while(!FileIsEnding(handle))
      content += FileReadString(handle) + "\n";
   FileClose(handle);
   return content;
}

//+------------------------------------------------------------------+
//| Участки набора позиции крупным участником                        |
//| Маленькие фиолетовые прямоугольники за свечами (BACK=true).      |
//+------------------------------------------------------------------+
void LoadAccumulationFromFile()
{
   if(!ShowAccumulation)
   {
      if(accumCount > 0) DeleteAccumulationObjects();
      return;
   }

   string content = ReadDataFile(AccumFilePath);
   if(StringLen(content) < 10) return;

   DeleteAccumulationObjects();

   int searchPos = 0;
   while(true)
   {
      int pos = StringFind(content, "\"t1\":", searchPos);
      if(pos < 0) break;

      datetime t1 = (datetime)(long)ExtractDouble(content, "\"t1\":", pos);
      datetime t2 = (datetime)(long)ExtractDouble(content, "\"t2\":", pos);
      double top    = ExtractDouble(content, "\"top\":", pos);
      double bottom = ExtractDouble(content, "\"bottom\":", pos);
      searchPos = pos + 5;

      if(t1 <= 0 || top <= 0 || bottom <= 0) continue;

      // Гарантируем видимую ширину даже для одиночного окна
      if(t2 <= t1) t2 = t1 + PeriodSeconds();

      string name = accumPrefix + IntegerToString(accumCount);
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, top, t2, bottom);
      ObjectSetInteger(0, name, OBJPROP_COLOR, AccumColor);
      ObjectSetInteger(0, name, OBJPROP_FILL, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      accumCount++;
   }

   if(accumCount != accumReported)
   {
      Print("[SmartZones MT5] Accumulation boxes drawn: ", accumCount);
      accumReported = accumCount;
   }
   DrawBuildStamp();
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
void DeleteAccumulationObjects()
{
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i);
      if(StringFind(name, accumPrefix) == 0)
         ObjectDelete(0, name);
   }
   accumCount = 0;
}

//+------------------------------------------------------------------+
void LoadZonesFromFile()
{
   int fileHandle = FileOpen(ZonesFilePath, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(fileHandle == INVALID_HANDLE)
   {
      fileHandle = FileOpen(ZonesFilePath, FILE_READ|FILE_TXT|FILE_ANSI);
      if(fileHandle == INVALID_HANDLE)
      {
         // Не спамим ошибками
         return;
      }
   }

   string content = "";
   while(!FileIsEnding(fileHandle))
   {
      content += FileReadString(fileHandle) + "\n";
   }
   FileClose(fileHandle);

   if(StringLen(content) < 10) return;

   DeleteAllZoneObjects();
   ParseZonesJSON(content);
   zonesCalcTime = ParseIsoTime(ExtractString(content, "\"calculated_at\":", 0));
   DrawAllZones();
   DrawBuildStamp();
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
void ParseZonesJSON(string json)
{
   currentZoneCount = 0;
   int searchPos = 0;

   while(true)
   {
      int pricePos = StringFind(json, "\"price\":", searchPos);
      if(pricePos < 0) break;

      double price  = ExtractDouble(json, "\"price\":", pricePos);
      double top    = ExtractDouble(json, "\"top\":", pricePos);
      double bottom = ExtractDouble(json, "\"bottom\":", pricePos);
      int    score  = (int)ExtractDouble(json, "\"score\":", pricePos);
      string label  = ExtractString(json, "\"label\":", pricePos);
      bool   bp     = (StringFind(json, "\"has_big_player\": true", pricePos) > 0 &&
                        StringFind(json, "\"has_big_player\": true", pricePos) < pricePos + 500);

      if(price > 0 && currentZoneCount < 20)
      {
         ArrayResize(zonePrices, currentZoneCount + 1);
         ArrayResize(zoneTops, currentZoneCount + 1);
         ArrayResize(zoneBottoms, currentZoneCount + 1);
         ArrayResize(zoneScores, currentZoneCount + 1);
         ArrayResize(zoneLabels, currentZoneCount + 1);
         ArrayResize(zoneBigPlayer, currentZoneCount + 1);

         zonePrices[currentZoneCount]    = price;
         zoneTops[currentZoneCount]      = top;
         zoneBottoms[currentZoneCount]   = bottom;
         zoneScores[currentZoneCount]    = score;
         zoneLabels[currentZoneCount]    = label;
         zoneBigPlayer[currentZoneCount] = bp;

         currentZoneCount++;
      }
      searchPos = pricePos + 10;
   }
   Print("[SmartZones MT5] Parsed ", currentZoneCount, " zones");
}

//+------------------------------------------------------------------+
double ExtractDouble(string json, string key, int startFrom)
{
   int keyPos = StringFind(json, key, startFrom);
   if(keyPos < 0) return 0;

   int valueStart = keyPos + StringLen(key);
   while(valueStart < StringLen(json) && StringGetCharacter(json, valueStart) == ' ')
      valueStart++;

   int valueEnd = valueStart;
   while(valueEnd < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, valueEnd);
      if(ch == ',' || ch == '}' || ch == '\n' || ch == '\r') break;
      valueEnd++;
   }

   string valueStr = StringSubstr(json, valueStart, valueEnd - valueStart);
   StringTrimRight(valueStr);
   StringTrimLeft(valueStr);
   return StringToDouble(valueStr);
}

//+------------------------------------------------------------------+
string ExtractString(string json, string key, int startFrom)
{
   int keyPos = StringFind(json, key, startFrom);
   if(keyPos < 0) return "";
   int quoteStart = StringFind(json, "\"", keyPos + StringLen(key));
   if(quoteStart < 0) return "";
   quoteStart++;
   int quoteEnd = StringFind(json, "\"", quoteStart);
   if(quoteEnd < 0) return "";
   return StringSubstr(json, quoteStart, quoteEnd - quoteStart);
}

//+------------------------------------------------------------------+
void DrawAllZones()
{
   for(int i = 0; i < currentZoneCount; i++)
      DrawSingleZone(i);
}

//+------------------------------------------------------------------+
void DrawSingleZone(int index)
{
   string baseName = zonePrefix + IntegerToString(index);
   double price    = zonePrices[index];
   double top      = zoneTops[index];
   double bottom   = zoneBottoms[index];
   int    score    = zoneScores[index];
   string label    = zoneLabels[index];

   color zoneColor;
   int lineWidth;
   if(score >= 11)      { zoneColor = ZoneColorStrong; lineWidth = ZoneLineWidth + 1; }
   else if(score >= 9)  { zoneColor = ZoneColorMedium; lineWidth = ZoneLineWidth; }
   else                 { zoneColor = ZoneColorWeak;   lineWidth = MathMax(1, ZoneLineWidth - 1); }

   // ── 1. Горизонтальная линия ──────────────────────────────────────
   string lineName = baseName + "_line";
   ObjectCreate(0, lineName, OBJ_HLINE, 0, 0, price);
   ObjectSetInteger(0, lineName, OBJPROP_COLOR, zoneColor);
   ObjectSetInteger(0, lineName, OBJPROP_WIDTH, lineWidth);
   ObjectSetInteger(0, lineName, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, lineName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, lineName, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, lineName, OBJPROP_BACK, true);

   // ── 3. Текстовая подпись ─────────────────────────────────────────
   if(ShowPriceLabels)
   {
      string textName = baseName + "_text";
      datetime textTime = iTime(_Symbol, PERIOD_CURRENT, 10);
      ObjectCreate(0, textName, OBJ_TEXT, 0, textTime, price + (top - price) * 0.3);
      // Только цена зоны (без источников/скора) — как просил клиент.
      ObjectSetString(0, textName, OBJPROP_TEXT, DoubleToString(price, 2));
      ObjectSetInteger(0, textName, OBJPROP_COLOR, clrWhite);
      ObjectSetString(0, textName, OBJPROP_FONT, "Arial Bold");
      ObjectSetInteger(0, textName, OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, textName, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
      ObjectSetInteger(0, textName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, textName, OBJPROP_HIDDEN, true);
   }

   // ── 3b. Бейдж со скором зоны ───────────────────────────────────
   if(ShowScoreBadge)
   {
      string badgeName = baseName + "_badge";
      datetime badgeTime = iTime(_Symbol, PERIOD_CURRENT, 0) + PeriodSeconds() * 4;
      ObjectCreate(0, badgeName, OBJ_TEXT, 0, badgeTime, price);
      ObjectSetString(0, badgeName, OBJPROP_TEXT,
                      " S:" + IntegerToString(score) + " ");
      ObjectSetInteger(0, badgeName, OBJPROP_COLOR, zoneColor);
      ObjectSetString(0, badgeName, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, badgeName, OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, badgeName, OBJPROP_ANCHOR, ANCHOR_LEFT);
      ObjectSetInteger(0, badgeName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, badgeName, OBJPROP_HIDDEN, true);
   }

   // ── 4. Structural SL Pool ─────────────────────────────────────────
   // SL is placed outside the zone using a bounded ATR buffer and the nearest
   // recent swing. It is a possible liquidity/stop level, not a trade signal.
   int lookback = (int)MathMin(Bars(_Symbol, PERIOD_CURRENT) - 2, 40);
   if(lookback < 5) lookback = 5;
   double atr = 0.0;
   int atrBars = (int)MathMin(Bars(_Symbol, PERIOD_CURRENT) - 2, 14);
   for(int i = 1; i <= atrBars; i++)
   {
      double hi = iHigh(_Symbol, PERIOD_CURRENT, i);
      double lo = iLow(_Symbol, PERIOD_CURRENT, i);
      double prevClose = iClose(_Symbol, PERIOD_CURRENT, i+1);
      atr += MathMax(hi - lo, MathMax(MathAbs(hi - prevClose), MathAbs(lo - prevClose)));
   }
   atr = atrBars > 0 ? atr / atrBars : (top - bottom);
   double zoneWidth = MathMax(MathAbs(top - bottom), _Point * 10.0);
   double buffer = MathMax(atr * 0.25, zoneWidth * 0.35);
   double swingLow = DBL_MAX;
   double swingHigh = -DBL_MAX;
   for(int i = 1; i <= lookback; i++)
   {
      swingLow = MathMin(swingLow, iLow(_Symbol, PERIOD_CURRENT, i));
      swingHigh = MathMax(swingHigh, iHigh(_Symbol, PERIOD_CURRENT, i));
   }
   double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   bool support = currentPrice > price;
   double zoneSL = support ? bottom - buffer : top + buffer;
   double structureSL = support ? swingLow - atr * 0.15 : swingHigh + atr * 0.15;
   // Choose the nearer valid structural level; never place SL inside the zone.
   double slLevel = support ? MathMax(zoneSL, structureSL) : MathMin(zoneSL, structureSL);
   slLevel = NormalizeDouble(slLevel, _Digits);

   int touchesFound = 0;
   for(int b = 1; b < (int)MathMin(Bars(_Symbol, PERIOD_CURRENT) - 1, 120); b++)
   {
      if(iLow(_Symbol, PERIOD_CURRENT, b) <= top && iHigh(_Symbol, PERIOD_CURRENT, b) >= bottom)
         touchesFound++;
   }
   int slProb = 35 + (int)MathMin(touchesFound * 4, 24);
   slProb += score >= 13 ? 16 : score >= 11 ? 11 : score >= 9 ? 6 : 0;
   slProb = (int)MathMin(slProb, 92);
   color slColor = support ? C'239,117,132' : C'119,228,208';
   string slLineName = baseName + "_sl_line";
   ObjectCreate(0, slLineName, OBJ_HLINE, 0, 0, slLevel);
   ObjectSetInteger(0, slLineName, OBJPROP_COLOR, slColor);
   ObjectSetInteger(0, slLineName, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, slLineName, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, slLineName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, slLineName, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, slLineName, OBJPROP_BACK, true);
   string slTextName = baseName + "_sl_label";
   datetime slTextTime = iTime(_Symbol, PERIOD_CURRENT, 0) + PeriodSeconds() * 80;
   ObjectCreate(0, slTextName, OBJ_TEXT, 0, slTextTime, slLevel);
   ObjectSetString(0, slTextName, OBJPROP_TEXT, " SL Pool " + DoubleToString(slLevel, _Digits) + " ~" + IntegerToString(slProb) + "%");
   ObjectSetInteger(0, slTextName, OBJPROP_COLOR, slColor);
   ObjectSetString(0, slTextName, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, slTextName, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, slTextName, OBJPROP_ANCHOR, ANCHOR_LEFT);
   ObjectSetInteger(0, slTextName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, slTextName, OBJPROP_HIDDEN, true);

}

//+------------------------------------------------------------------+
//| Градиентная визуализация зоны                                     |
//| Рисует несколько слоёв прямоугольников с убывающей прозрачностью  |
//| Центр — ярко-красный, края — полупрозрачные                      |
//+------------------------------------------------------------------+
void DrawGradientZone(string baseName, double price, double top, double bottom,
                      color baseColor, int score)
{
   int layers = GradientLayers;
   double zoneHeight = top - bottom;
   double layerStep  = zoneHeight / (2.0 * layers);

   datetime timeLeft  = iTime(_Symbol, PERIOD_CURRENT, MathMin(Bars(_Symbol, PERIOD_CURRENT) - 1, 200));
   datetime timeRight = iTime(_Symbol, PERIOD_CURRENT, 0) + PeriodSeconds() * 50;

   // Градация цветов от яркого (центр) к бледному (края)
   // MQL5 не поддерживает alpha, поэтому используем разные оттенки красного
   color gradColors[];
   ArrayResize(gradColors, layers);

   // Генерируем градиент: центр = baseColor, края = более светлый
   int r_base = (int)((baseColor) & 0xFF);
   int g_base = (int)((baseColor >> 8) & 0xFF);
   int b_base = (int)((baseColor >> 16) & 0xFF);

   for(int i = 0; i < layers; i++)
   {
      double fade = (double)i / (double)(layers - 1);  // 0.0 (центр) → 1.0 (край)
      int r = r_base + (int)((255 - r_base) * fade * 0.7);
      int g = g_base + (int)((255 - g_base) * fade * 0.7);
      int b = b_base + (int)((255 - b_base) * fade * 0.7);
      r = MathMin(r, 255);
      g = MathMin(g, 255);
      b = MathMin(b, 255);

      gradColors[i] = (color)((b << 16) | (g << 8) | r);
   }

   // Рисуем слои от краёв к центру
   for(int i = layers - 1; i >= 0; i--)
   {
      string rectName = baseName + "_grad_" + IntegerToString(i);
      double layerTop    = price + layerStep * (i + 1);
      double layerBottom = price - layerStep * (i + 1);

      // Ограничиваем границами зоны
      layerTop    = MathMin(layerTop, top);
      layerBottom = MathMax(layerBottom, bottom);

      ObjectCreate(0, rectName, OBJ_RECTANGLE, 0, timeLeft, layerTop, timeRight, layerBottom);
      ObjectSetInteger(0, rectName, OBJPROP_COLOR, gradColors[i]);
      ObjectSetInteger(0, rectName, OBJPROP_FILL, true);
      ObjectSetInteger(0, rectName, OBJPROP_BACK, true);
      ObjectSetInteger(0, rectName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, rectName, OBJPROP_HIDDEN, true);
   }
}

//+------------------------------------------------------------------+
void DeleteAllZoneObjects()
{
   int total = ObjectsTotal(0);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i);
      // Участки набора живут своей жизнью (свой файл и своя перерисовка)
      if(StringFind(name, accumPrefix) == 0) continue;
      if(StringFind(name, buildPrefix) == 0) continue;
      if(StringFind(name, zonePrefix) == 0)
         ObjectDelete(0, name);
   }
   currentZoneCount = 0;
   ArrayFree(zonePrices);
   ArrayFree(zoneTops);
   ArrayFree(zoneBottoms);
   ArrayFree(zoneScores);
   ArrayFree(zoneLabels);
   ArrayFree(zoneBigPlayer);
}

//+------------------------------------------------------------------+
void CheckAlerts()
{
   if(TimeCurrent() - lastAlertTime < 300) return;

   double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   for(int i = 0; i < currentZoneCount; i++)
   {
      double dist = MathAbs(currentPrice - zonePrices[i]);
      if(dist <= AlertDistance)
      {
         string direction = currentPrice > zonePrices[i] ? "ABOVE" : "BELOW";
         string msg = StringFormat(
            "[SmartZones] Price %.2f is %.1f$ %s zone %.2f (S:%d)",
            currentPrice, dist, direction, zonePrices[i], zoneScores[i]
         );

         Alert(msg);
         SendNotification(msg);
         lastAlertTime = TimeCurrent();
         break;
      }
   }
}
//+------------------------------------------------------------------+
