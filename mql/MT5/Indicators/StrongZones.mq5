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
input color    ZoneColorFallback = clrTomato;      // Сомнительный fallback-уровень
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
input bool     ShowSLCloud      = true;          // Показывать структурные области SL из Python Core
input int      SLCloudPoints    = 9;             // Устаревший параметр: сохранён для совместимости профилей
input int      SLAreaForwardBars = 80;           // Длина области SL вправо по графику
input double   SLAreaDepthMultiplier = 4.5;      // Глубина области относительно структурного буфера
input color    SLLongAreaColor  = C'45,135,90';  // Приглушённый зелёный: Long SL под поддержкой
input color    SLShortAreaColor = C'160,65,70';  // Приглушённый красный: Short SL над сопротивлением

//--- Глобальные переменные -------------------------------------------
string         zonePrefix       = "SZP_";
string         accumPrefix      = "SZP_ACC_";
string         buildPrefix      = "SZP_VER_";
int            currentZoneCount = 0;
int            accumCount       = 0;
int            accumReported    = -1;
int            slCloudCount    = 0;
int            slLocalAnchorCount = 0;
datetime       zonesCalcTime    = 0;
datetime       lastFileTime     = 0;         // Последний успешно применённый payload
long           lastFileSize     = -1;        // Размер последнего успешно применённого payload
datetime       lastAlertTime    = 0;
double         referencePrice   = 0;
string         payloadProducerBuild = "";
string         payloadId       = "";
string         payloadError    = "";

double         zonePrices[];
double         zoneTops[];
double         zoneBottoms[];
int            zoneScores[];
string         zoneLabels[];
bool           zoneBigPlayer[];
bool           zoneFallback[];
double         stopPrices[];
double         stopBuffers[];
int            stopProbabilities[];
string         stopSides[];
datetime       stopAnchorTimes[];
double         stopAnchorPrices[];


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
   if(payloadProducerBuild != "") text += "  |  src: " + payloadProducerBuild;
   if(payloadId != "") text += "  |  payload: " + StringSubstr(payloadId, 0, 8);
   if(payloadError != "")
   {
      text += "  |  ERROR: " + payloadError;
      clr = clrTomato;
   }

   if(zonesCalcTime > 0)
   {
      int ageMin = (int)((TimeLocal() - zonesCalcTime) / 60);
      string age = ageMin < 60 ? IntegerToString(ageMin) + "m"
                              : IntegerToString(ageMin / 60) + "h";
      text += "  |  zones: " + IntegerToString(currentZoneCount) +
              "  sl-areas: " + IntegerToString(slCloudCount) +
              (slLocalAnchorCount > 0 ? "  sl-local: " + IntegerToString(slLocalAnchorCount) : "") +
              "  acc: " + IntegerToString(accumCount) +
              "  " + age + " ago";
      if(referencePrice > 0)
         text += "  |  ref: " + DoubleToString(referencePrice, _Digits);
      if(ageMin > 360) clr = clrTomato;
   }
   else
      text += "  |  no zones file";

   string name = buildPrefix + "STAMP";
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 8);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 25);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_RIGHT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
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
   if(FileHasChanged())
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
//| A timer event is not a data update: reload only a changed payload. |
//+------------------------------------------------------------------+
bool FileHasChanged()
{
   int fileHandle = FileOpen(ZonesFilePath, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(fileHandle == INVALID_HANDLE)
      fileHandle = FileOpen(ZonesFilePath, FILE_READ|FILE_TXT|FILE_ANSI);
   if(fileHandle == INVALID_HANDLE)
      return false;

   datetime modified = (datetime)FileGetInteger(fileHandle, FILE_MODIFY_DATE);
   long size = (long)FileGetInteger(fileHandle, FILE_SIZE);
   FileClose(fileHandle);
   return lastFileTime == 0 || modified != lastFileTime || size != lastFileSize;
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

   // Store identity only after a complete six-zone payload is accepted.
   datetime fileModified = (datetime)FileGetInteger(fileHandle, FILE_MODIFY_DATE);
   long fileSize = (long)FileGetInteger(fileHandle, FILE_SIZE);

   string content = "";
   while(!FileIsEnding(fileHandle))
   {
      content += FileReadString(fileHandle) + "\n";
   }
   FileClose(fileHandle);

   if(StringLen(content) < 10) return;

   payloadError = "";
   if(!ValidatePayloadHeader(content))
   {
      // Preserve the last valid render if a just-replaced payload is incomplete
      // or belongs to another schema/build.
      DrawBuildStamp();
      return;
   }
   zonesCalcTime = ParseIsoTime(ExtractString(content, "\"calculated_at\":", 0));
   referencePrice = ExtractDouble(content, "\"reference_price\":", 0);
   payloadProducerBuild = ExtractString(content, "\"producer_build\":", 0);
   payloadId = ExtractString(content, "\"payload_id\":", 0);

   if(!ParseZonesJSON(content))
   {
      // Parsing failure must not blank the last known-good six lines.
      DrawBuildStamp();
      return;
   }

   // Commit the new objects only after parsing validates six levels (3+3).
   // Keep the freshly parsed arrays while removing the previous chart objects.
   DeleteAllZoneObjects(false);
   DrawAllZones();
   lastFileTime = fileModified;
   lastFileSize = fileSize;
   DrawBuildStamp();
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
bool ValidatePayloadHeader(string json)
{
   string schema = ExtractString(json, "\"schema_version\":", 0);
   string kind = ExtractString(json, "\"payload_kind\":", 0);
   if(schema != "4.0" || kind != "szp_active_zones")
   {
      payloadError = "incompatible payload schema";
      Print("[SmartZones MT5] ", payloadError, ": ", schema, " / ", kind);
      return false;
   }
   if(ExtractDouble(json, "\"reference_price\":", 0) <= 0)
   {
      payloadError = "missing reference price";
      return false;
   }
   return true;
}

// Strict parser: only unique top-level `zone_*` keys are accepted. Nested
// `stop_price` and any unrelated object cannot consume a display slot.
bool ParseZonesJSON(string json)
{
   currentZoneCount = 0;
   int searchPos = 0;
   int above = 0;
   int below = 0;

   while(true)
   {
      int pricePos = StringFind(json, "\"zone_price\":", searchPos);
      if(pricePos < 0) break;
      int nextZone = StringFind(json, "\"zone_price\":", pricePos + 13);

      double price  = ExtractDouble(json, "\"zone_price\":", pricePos);
      double top    = ExtractDouble(json, "\"zone_top\":", pricePos);
      double bottom = ExtractDouble(json, "\"zone_bottom\":", pricePos);
      int    score  = (int)ExtractDouble(json, "\"zone_score\":", pricePos);
      string label  = ExtractString(json, "\"zone_label\":", pricePos);
      double stopPrice = ExtractDouble(json, "\"stop_price\":", pricePos);
      double stopBuffer = ExtractDouble(json, "\"stop_buffer\":", pricePos);
      int stopProbability = (int)ExtractDouble(json, "\"stop_probability\":", pricePos);
      string stopSide = ExtractString(json, "\"stop_side\":", pricePos);
      datetime stopAnchorTime = (datetime)(long)ExtractDouble(json, "\"stop_anchor_epoch\":", pricePos);
      double stopAnchorPrice = ExtractDouble(json, "\"stop_anchor_price\":", pricePos);
      int flagPos   = StringFind(json, "\"zone_fallback\": true", pricePos);
      bool fallback = (flagPos >= pricePos && (nextZone < 0 || flagPos < nextZone));
      int bpPos     = StringFind(json, "\"zone_has_big_player\": true", pricePos);
      bool bp       = (bpPos >= pricePos && (nextZone < 0 || bpPos < nextZone));

      // A missing swing anchor is a legacy/upgrade condition, not a reason
      // to suppress six validated zones. Only cloud rendering is deferred.
      if(price <= 0 || top < price || bottom > price || stopPrice <= 0 || currentZoneCount >= 6)
      {
         payloadError = "invalid zone record";
         return false;
      }
      ArrayResize(zonePrices, currentZoneCount + 1);
      ArrayResize(zoneTops, currentZoneCount + 1);
      ArrayResize(zoneBottoms, currentZoneCount + 1);
      ArrayResize(zoneScores, currentZoneCount + 1);
      ArrayResize(zoneLabels, currentZoneCount + 1);
      ArrayResize(zoneBigPlayer, currentZoneCount + 1);
      ArrayResize(zoneFallback, currentZoneCount + 1);
      ArrayResize(stopPrices, currentZoneCount + 1);
      ArrayResize(stopBuffers, currentZoneCount + 1);
      ArrayResize(stopProbabilities, currentZoneCount + 1);
      ArrayResize(stopSides, currentZoneCount + 1);
      ArrayResize(stopAnchorTimes, currentZoneCount + 1);
      ArrayResize(stopAnchorPrices, currentZoneCount + 1);
      zonePrices[currentZoneCount] = price;
      zoneTops[currentZoneCount] = top;
      zoneBottoms[currentZoneCount] = bottom;
      zoneScores[currentZoneCount] = score;
      zoneLabels[currentZoneCount] = label;
      zoneBigPlayer[currentZoneCount] = bp;
      zoneFallback[currentZoneCount] = fallback;
      stopPrices[currentZoneCount] = stopPrice;
      stopBuffers[currentZoneCount] = stopBuffer;
      stopProbabilities[currentZoneCount] = stopProbability;
      stopSides[currentZoneCount] = stopSide;
      stopAnchorTimes[currentZoneCount] = stopAnchorTime;
      stopAnchorPrices[currentZoneCount] = stopAnchorPrice;
      currentZoneCount++;
      if(price > referencePrice) above++;
      if(price < referencePrice) below++;
      if(nextZone < 0) break;
      searchPos = nextZone;
   }
   if(currentZoneCount != 6 || above != 3 || below != 3)
   {
      payloadError = "display contract is not 3+3";
      Print("[SmartZones MT5] ", payloadError, ": ", above, " above / ", below, " below");
      return false;
   }
   Print("[SmartZones MT5] Parsed six schema-4 zones: 3 above / 3 below");
   return true;
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

   bool  fallback = zoneFallback[index];
   color zoneColor;
   int lineWidth;
   if(fallback)         { zoneColor = ZoneColorFallback; lineWidth = MathMax(1, ZoneLineWidth - 1); }
   else if(score >= 11) { zoneColor = ZoneColorStrong;   lineWidth = ZoneLineWidth + 1; }
   else if(score >= 9)  { zoneColor = ZoneColorMedium;   lineWidth = ZoneLineWidth; }
   else                 { zoneColor = ZoneColorWeak;     lineWidth = MathMax(1, ZoneLineWidth - 1); }

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

   if(ShowSLCloud)
      DrawStopArea(baseName, index);

}

//+------------------------------------------------------------------+
//| Structural SL cloud from Python Core: green = long, red = short |
//+------------------------------------------------------------------+
// Resolve a legacy payload without `stop_anchor_*` against the visible
// market history. This remains structural: low nearest support / high nearest
// resistance, never an arbitrary point at the chart edge.
datetime ResolveStopAnchor(int index, double &anchorPrice)
{
   if(stopAnchorTimes[index] > 0 && stopAnchorPrices[index] > 0)
   {
      anchorPrice = stopAnchorPrices[index];
      return stopAnchorTimes[index];
   }
   bool isLong = (stopSides[index] == "BELOW_SUPPORT");
   double target = isLong ? zoneBottoms[index] : zoneTops[index];
   int barsToScan = MathMin(Bars(_Symbol, PERIOD_CURRENT) - 1, 400);
   double bestDistance = 1.0e100;
   int bestShift = -1;
   for(int shift = 1; shift <= barsToScan; shift++)
   {
      double extreme = isLong ? iLow(_Symbol, PERIOD_CURRENT, shift)
                              : iHigh(_Symbol, PERIOD_CURRENT, shift);
      double distance = MathAbs(extreme - target);
      if(distance < bestDistance)
      {
         bestDistance = distance;
         bestShift = shift;
         anchorPrice = extreme;
      }
   }
   if(bestShift < 0) return 0;
   slLocalAnchorCount++;
   return iTime(_Symbol, PERIOD_CURRENT, bestShift);
}

void DrawStopArea(string baseName, int index)
{
   double stopPrice = stopPrices[index];
   if(stopPrice <= 0) return;

   // Python marks a support stop as BELOW_SUPPORT (Long) and a resistance
   // stop as ABOVE_RESISTANCE (Short). Keep the risk area on that side only.
   bool isLong = (stopSides[index] == "BELOW_SUPPORT");
   color areaColor = isLong ? SLLongAreaColor : SLShortAreaColor;
   double buffer = MathMax(stopBuffers[index], _Point * 12.0);
   double depth = MathMax(buffer * SLAreaDepthMultiplier,
                          MathAbs(zoneTops[index] - zoneBottoms[index]) * 1.5);
   double nearEdge, farEdge;
   if(isLong)
   {
      nearEdge = MathMin(zoneBottoms[index] - buffer * 0.10, stopPrice + buffer * 0.35);
      farEdge = MathMin(stopPrice - depth, nearEdge - buffer);
   }
   else
   {
      nearEdge = MathMax(zoneTops[index] + buffer * 0.10, stopPrice - buffer * 0.35);
      farEdge = MathMax(stopPrice + depth, nearEdge + buffer);
   }

   // Objects have no reliable alpha across MT5 terminal themes. A muted fill
   // behind candles reproduces the transparent rectangular SL area safely.
   int availableBars = Bars(_Symbol, PERIOD_CURRENT);
   if(availableBars < 2) return;
   int barsBack = MathMin(availableBars - 1, 12);
   datetime timeStart = iTime(_Symbol, PERIOD_CURRENT, barsBack);
   datetime timeEnd = iTime(_Symbol, PERIOD_CURRENT, 0) +
                      PeriodSeconds() * MathMax(12, SLAreaForwardBars);
   string areaName = baseName + "_sl_area";
   ObjectCreate(0, areaName, OBJ_RECTANGLE, 0, timeStart, nearEdge, timeEnd, farEdge);
   ObjectSetInteger(0, areaName, OBJPROP_COLOR, areaColor);
   ObjectSetInteger(0, areaName, OBJPROP_FILL, true);
   ObjectSetInteger(0, areaName, OBJPROP_BACK, true);
   ObjectSetInteger(0, areaName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, areaName, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, areaName, OBJPROP_STYLE, STYLE_SOLID);
   slCloudCount++;

   string labelName = baseName + "_sl_area_label";
   ObjectCreate(0, labelName, OBJ_TEXT, 0,
                iTime(_Symbol, PERIOD_CURRENT, 0) + PeriodSeconds() * 4,
                (nearEdge + farEdge) / 2.0);
   ObjectSetString(0, labelName, OBJPROP_TEXT, (isLong ? " LONG SL AREA " : " SHORT SL AREA ") +
                   DoubleToString(stopPrice, _Digits) + " ~" + IntegerToString(stopProbabilities[index]) + "%");
   ObjectSetInteger(0, labelName, OBJPROP_COLOR, areaColor);
   ObjectSetString(0, labelName, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, labelName, OBJPROP_ANCHOR, ANCHOR_LEFT);
   ObjectSetInteger(0, labelName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, labelName, OBJPROP_HIDDEN, true);
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
void DeleteAllZoneObjects(bool resetData = true)
{
   int total = ObjectsTotal(0);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i);
      // Участки набора живут своей жизнью (свой файл и своя перерисовка)
      if(StringFind(name, accumPrefix) == 0) continue;
      if(StringFind(name, buildPrefix) == 0) continue;
      if(name == zonePrefix + "FP_BTN") continue;
      if(StringFind(name, zonePrefix) == 0)
         ObjectDelete(0, name);
   }
   if(!resetData) return;
   currentZoneCount = 0;
   slCloudCount = 0;
   slLocalAnchorCount = 0;
   ArrayFree(zonePrices);
   ArrayFree(zoneTops);
   ArrayFree(zoneBottoms);
   ArrayFree(zoneScores);
   ArrayFree(zoneLabels);
   ArrayFree(zoneBigPlayer);
   ArrayFree(zoneFallback);
   ArrayFree(stopPrices);
   ArrayFree(stopBuffers);
   ArrayFree(stopProbabilities);
   ArrayFree(stopSides);
   ArrayFree(stopAnchorTimes);
   ArrayFree(stopAnchorPrices);
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
