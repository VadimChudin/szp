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

//--- Настройки (Input Parameters) ------------------------------------
input string   ZonesFilePath    = "zones_output.json";   // Имя файла с зонами (в Common/Files)
input int      RefreshSeconds   = 10;         // Интервал обновления (сек)
input color    ZoneColorStrong  = clrGold;        // Цвет сильных зон (Score >= 11)
input color    ZoneColorMedium  = C'200,170,60';  // Цвет средних зон
input color    ZoneColorWeak    = C'120,110,80';  // Цвет слабых зон
input int      ZoneLineWidth    = 2;          // Толщина линии
input bool     ShowLabels       = true;       // Показывать подписи
input bool     ShowRectangles   = true;       // Полупрозрачные прямоугольники зон
input bool     ShowScoreBadge   = true;       // Бейдж со скором
input bool     ShowGradient     = false;      // Градиентная визуализация (выкл. по умолчанию)
input int      GradientLayers   = 5;          // Кол-во слоёв градиента
input bool     EnableAlerts     = true;       // Алерты при касании зоны
input double   AlertDistance    = 5.0;        // Расстояние для алерта ($)

//--- Глобальные переменные -------------------------------------------
string         zonePrefix       = "SZP_";
int            currentZoneCount = 0;
datetime       lastAlertTime    = 0;

double         zonePrices[];
double         zoneTops[];
double         zoneBottoms[];
int            zoneScores[];
string         zoneLabels[];
bool           zoneBigPlayer[];


//+------------------------------------------------------------------+
int OnInit()
{
   EventSetTimer(RefreshSeconds);
   LoadZonesFromFile();
   Print("[SmartZones MT5] Initialized. File: ", ZonesFilePath);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   DeleteAllZoneObjects();
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
   DrawAllZones();
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

   // ── 2. Градиентные прямоугольники ────────────────────────────────
   if(ShowRectangles && ShowGradient)
   {
      DrawGradientZone(baseName, price, top, bottom, zoneColor, score);
   }
   else if(ShowRectangles)
   {
      // Приглушённый полупрозрачный прямоугольник (MT5 не имеет
      // альфы для OBJ_RECTANGLE — используем тёмный цвет + BACK=true).
      string rectName = baseName + "_rect";
      int totalBars = Bars(_Symbol, PERIOD_CURRENT);
      int leftIdx   = (int)MathMin(totalBars - 1, 120);
      datetime timeLeft  = iTime(_Symbol, PERIOD_CURRENT, leftIdx);
      datetime timeRight = iTime(_Symbol, PERIOD_CURRENT, 0) + PeriodSeconds() * 30;

      color rectFill;
      if(score >= 11)      rectFill = (color)C'80,70,30';
      else if(score >= 9)  rectFill = (color)C'55,50,30';
      else                 rectFill = (color)C'40,40,35';

      ObjectCreate(0, rectName, OBJ_RECTANGLE, 0, timeLeft, top, timeRight, bottom);
      ObjectSetInteger(0, rectName, OBJPROP_COLOR, rectFill);
      ObjectSetInteger(0, rectName, OBJPROP_FILL, true);
      ObjectSetInteger(0, rectName, OBJPROP_BACK, true);
      ObjectSetInteger(0, rectName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, rectName, OBJPROP_HIDDEN, true);
   }

   // ── 3. Текстовая подпись ─────────────────────────────────────────
   if(ShowLabels)
   {
      string textName = baseName + "_text";
      datetime textTime = iTime(_Symbol, PERIOD_CURRENT, 10);
      ObjectCreate(0, textName, OBJ_TEXT, 0, textTime, price + (top - price) * 0.3);
      ObjectSetString(0, textName, OBJPROP_TEXT, " " + label + " ");
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
