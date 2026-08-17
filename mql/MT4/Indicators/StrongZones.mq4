//+------------------------------------------------------------------+
//|                                              StrongZones.mq4     |
//|                                          Smart Zones Pro v1.0    |
//|                                                                  |
//| Индикатор сильных зон для XAU/USD                                |
//| Читает зоны из JSON-файла, сгенерированного Python Core,        |
//| и отрисовывает их на графике в виде красных линий/прямоугольников|
//+------------------------------------------------------------------+
#property copyright "Smart Zones Pro"
#property link      ""
#property version   "1.00"
#property strict
#property indicator_chart_window

// Номер сборки подставляет CI при компиляции: без него нельзя было понять,
// какая версия индикатора реально загружена в терминале клиента.
#define SZP_BUILD "dev"

//--- Настройки (Input Parameters) ------------------------------------
input int      RefreshSeconds   = 10;        // Интервал обновления (сек)
input color    ZoneColorStrong  = clrGold;   // Цвет сильных зон (Score >= 11)
input color    ZoneColorMedium  = C'200,170,60';  // Цвет средних зон (Score 9-10)
input color    ZoneColorWeak    = C'120,110,80';  // Цвет слабых зон
input color    ZoneColorFallback = clrTomato;      // Сомнительный fallback-уровень
input int      ZoneLineWidth    = 2;         // Толщина линии зоны
// Параметр переименован из ShowLabels: терминал хранит значения инпутов в
// профиле графика, и у клиентов оставался ShowLabels=false из старой сборки —
// цены на уровнях не появлялись даже после обновления индикатора.
input bool     ShowPriceLabels  = true;      // Показывать только цену зоны
input bool     ShowRectangles   = false;      // Полупрозрачные прямоугольники зон
input bool     ShowScoreBadge   = false;     // Показывать бейдж со скором зоны
input bool     EnableAlerts     = true;      // Алерты при касании зоны
input double   AlertDistance    = 5.0;       // Расстояние до зоны для алерта ($)
// Имя файла с зонами — лежит в MQL4/Files или Common/Files (положит sync_zones_to_mt4.py).
input string   ZonesFilePath    = "zones_output.json";
input bool     ShowAccumulation = true;      // Набор позиции крупным участником
input string   AccumFilePath    = "accumulation_output.json"; // Файл участков набора
input color    AccumColor       = C'85,45,140';  // Цвет участков набора (фиолетовый)
input bool     ShowSLCloud      = true;          // Облако структурного SL из Python Core
input int      SLCloudPoints    = 9;             // Количество точек в облаке SL

//--- Глобальные переменные -------------------------------------------
datetime       lastFileTime     = 0;         // Время последнего изменения файла
datetime       lastAlertTime    = 0;         // Время последнего алерта
string         zonePrefix       = "SZP_";    // Префикс объектов индикатора
string         accumPrefix      = "SZP_ACC_"; // Префикс участков набора
string         buildPrefix      = "SZP_VER_"; // Префикс метки сборки
int            currentZoneCount = 0;         // Текущее количество зон на графике
int            accumCount       = 0;         // Количество участков набора
int            accumReported    = -1;        // Последнее залогированное количество
datetime       zonesCalcTime    = 0;         // Когда Python посчитал зоны
double         referencePrice   = 0;         // Цена, относительно которой выбран snapshot
string         payloadProducerBuild = "";
string         payloadId       = "";
string         payloadError    = "";

// Храним данные зон в массивах
double         zonePrices[];
double         zoneTops[];
double         zoneBottoms[];
int            zoneScores[];
string         zoneLabels[];
bool           zoneFallback[];
double         stopPrices[];
double         stopBuffers[];
int            stopProbabilities[];
string         stopSides[];


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
//| Метка в углу графика: версия сборки, число зон/участков и     |
//| возраст данных. Старый JSON подсвечивается красным: именно так  |
//| выглядит «зоны те же» — приложение больше не считает.        |
//+------------------------------------------------------------------+
void DrawBuildStamp()
{
   string text = "SZP v" + SZP_BUILD;
   color  clr  = C'110,110,110';
   if(payloadProducerBuild != "") text = text + "  |  src: " + payloadProducerBuild;
   if(payloadId != "") text = text + "  |  payload: " + StringSubstr(payloadId, 0, 8);
   if(payloadError != "")
   {
      text = text + "  |  ERROR: " + payloadError;
      clr = clrTomato;
   }

   if(zonesCalcTime > 0)
   {
      int ageMin = (int)((TimeLocal() - zonesCalcTime) / 60);
      string age = IntegerToString(ageMin) + "m";
      if(ageMin >= 60) age = IntegerToString(ageMin / 60) + "h";
      text = text + "  |  zones: " + IntegerToString(currentZoneCount) +
             "  acc: " + IntegerToString(accumCount) + "  " + age + " ago";
      if(referencePrice > 0)
         text = text + "  |  ref: " + DoubleToString(referencePrice, Digits);
      if(ageMin > 360) clr = clrTomato;
   }
   else
      text = text + "  |  no zones file";

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
//| Custom indicator initialization function                          |
//+------------------------------------------------------------------+
int OnInit()
{
   // Чистим объекты сразу при инициализации (в т.ч. при смене ТФ). Иначе
   // подписи/объекты, сохранённые в профиле графика от прежней версии
   // индикатора, «мигают» до первой успешной загрузки JSON.
   DeleteAllZoneObjects();
   DeleteAccumulationObjects();

   // Таймер для периодического обновления
   EventSetTimer(RefreshSeconds);
   
   // Первая загрузка зон
   LoadZonesFromFile();
   LoadAccumulationFromFile();
   
   // ── Создаём кнопку "FP" (Footprint) на графике ──────────────────
   string btnName = zonePrefix + "FP_BTN";
   ObjectCreate(0, btnName, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, btnName, OBJPROP_XDISTANCE, 10);
   ObjectSetInteger(0, btnName, OBJPROP_YDISTANCE, 50);
   ObjectSetInteger(0, btnName, OBJPROP_XSIZE, 50);
   ObjectSetInteger(0, btnName, OBJPROP_YSIZE, 28);
   ObjectSetString(0, btnName, OBJPROP_TEXT, "FP");
   ObjectSetString(0, btnName, OBJPROP_FONT, "Arial Bold");
   ObjectSetInteger(0, btnName, OBJPROP_FONTSIZE, 10);
   ObjectSetInteger(0, btnName, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, btnName, OBJPROP_BGCOLOR, C'40,40,40');
   ObjectSetInteger(0, btnName, OBJPROP_BORDER_COLOR, C'80,80,80');
   ObjectSetInteger(0, btnName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, btnName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, btnName, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, btnName, OBJPROP_STATE, false);
   
   DrawBuildStamp();

   Print("[SmartZones] Indicator initialized, build v", SZP_BUILD,
         ". Reading zones from MQL4/Files/", ZonesFilePath);
   Print("[SmartZones] Refresh interval: ", RefreshSeconds, " seconds");
   Print("[SmartZones] Footprint button [FP] created");
   
   return(INIT_SUCCEEDED);
}


//+------------------------------------------------------------------+
//| Custom indicator deinitialization function                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // Удаляем все объекты индикатора
   DeleteAllZoneObjects();
   DeleteAccumulationObjects();
   // Удаляем кнопку FP и метку сборки
   ObjectDelete(0, zonePrefix + "FP_BTN");
   ObjectDelete(0, buildPrefix + "STAMP");
   EventKillTimer();
   Print("[SmartZones] Indicator removed. Cleaned up ", currentZoneCount, " zones.");
}


//+------------------------------------------------------------------+
//| Custom indicator iteration function                               |
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
   // Проверяем алерты при каждом тике
   if(EnableAlerts && currentZoneCount > 0)
      CheckAlerts();
   
   return(rates_total);
}


//+------------------------------------------------------------------+
//| Обработка событий графика (клик по кнопке FP)                     |
//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   if(id == CHARTEVENT_OBJECT_CLICK)
   {
      string btnName = zonePrefix + "FP_BTN";
      if(sparam == btnName)
      {
         // Отжимаем кнопку визуально
         ObjectSetInteger(0, btnName, OBJPROP_STATE, false);
         
         // Определяем текущий таймфрейм
         string fpInterval = "4h";
         int per = Period();
         if(per <= PERIOD_H1) fpInterval = "1h";
         else if(per <= PERIOD_H4) fpInterval = "4h";
         else fpInterval = "1d";
         
         // Записываем файл-флаг для Python Bridge в общую папку терминала
         // (Terminal\Common\Files), откуда его читает bridge_server.
         int fh = FileOpen("footprint_request.flag", FILE_WRITE|FILE_TXT|FILE_COMMON);
         if(fh != INVALID_HANDLE)
         {
            FileWriteString(fh, fpInterval);
            FileClose(fh);
            Print("[SmartZones] Footprint requested: ", fpInterval);
         }
         else
         {
            Print("[SmartZones] ERROR: Cannot write footprint flag");
         }
         
         ChartRedraw();
      }
   }
}


//+------------------------------------------------------------------+
//| Timer - периодическая проверка обновлений файла                   |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Проверяем, изменился ли файл с зонами
   if(FileHasChanged())
   {
      Print("[SmartZones] File updated. Reloading zones...");
      LoadZonesFromFile();
   }
   LoadAccumulationFromFile();
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

   int fileHandle = FileOpen(AccumFilePath, FILE_READ|FILE_TXT|FILE_COMMON);
   if(fileHandle == INVALID_HANDLE)
   {
      fileHandle = FileOpen(AccumFilePath, FILE_READ|FILE_TXT);
      if(fileHandle == INVALID_HANDLE) return;
   }

   string content = "";
   while(!FileIsEnding(fileHandle))
      content += FileReadString(fileHandle) + "\n";
   FileClose(fileHandle);

   if(StringLen(content) < 10) return;

   DeleteAccumulationObjects();

   int searchPos = 0;
   while(true)
   {
      int pos = StringFind(content, "\"t1\":", searchPos);
      if(pos < 0) break;

      datetime t1   = (datetime)(long)ExtractDouble(content, "\"t1\":", pos);
      datetime t2   = (datetime)(long)ExtractDouble(content, "\"t2\":", pos);
      double top    = ExtractDouble(content, "\"top\":", pos);
      double bottom = ExtractDouble(content, "\"bottom\":", pos);
      searchPos = pos + 5;

      if(t1 <= 0 || top <= 0 || bottom <= 0) continue;

      // Гарантируем видимую ширину даже для одиночного окна
      if(t2 <= t1) t2 = t1 + PeriodSeconds();

      string name = accumPrefix + IntegerToString(accumCount);
      ObjectCreate(name, OBJ_RECTANGLE, 0, t1, top, t2, bottom);
      ObjectSetInteger(0, name, OBJPROP_COLOR, AccumColor);
      ObjectSetInteger(0, name, OBJPROP_FILL, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      accumCount++;
   }

   if(accumCount != accumReported)
   {
      Print("[SmartZones] Accumulation boxes drawn: ", accumCount);
      accumReported = accumCount;
   }
   DrawBuildStamp();
   ChartRedraw();
}


//+------------------------------------------------------------------+
//| Удаление прямоугольников набора позиции                          |
//+------------------------------------------------------------------+
void DeleteAccumulationObjects()
{
   for(int i = ObjectsTotal() - 1; i >= 0; i--)
   {
      string name = ObjectName(i);
      if(StringFind(name, accumPrefix) == 0)
         ObjectDelete(name);
   }
   accumCount = 0;
}


//+------------------------------------------------------------------+
//| Проверка изменения файла                                          |
//+------------------------------------------------------------------+
bool FileHasChanged()
{
   // Проверяем через WinAPI время изменения файла
   // В MQL4 можно использовать простой подход: читаем и сравниваем
   int fileHandle = FileOpen("smart_zones_check.tmp", FILE_WRITE|FILE_TXT);
   if(fileHandle != INVALID_HANDLE)
      FileClose(fileHandle);
   
   return true;  // Для простоты перечитываем каждый раз
}


//+------------------------------------------------------------------+
//| Загрузка зон из JSON файла                                        |
//+------------------------------------------------------------------+
void LoadZonesFromFile()
{
   // Читаем файл через прямой доступ к файловой системе
   // MQL4 может читать файлы только из папки MQL4/Files/
   // Поэтому используем общую папку терминала
   
   string filename = "zones_output.json";
   
   int fileHandle = FileOpen(filename, FILE_READ|FILE_TXT|FILE_COMMON);
   if(fileHandle == INVALID_HANDLE)
   {
      // Пробуем без FILE_COMMON
      fileHandle = FileOpen(filename, FILE_READ|FILE_TXT);
      if(fileHandle == INVALID_HANDLE)
      {
         Print("[SmartZones] WARNING: Cannot open ", filename, 
               " Error: ", GetLastError(),
               " Copy zones_output.json to MT4/MQL4/Files/ or Common/Files/");
         return;
      }
   }
   
   // Читаем весь файл
   string content = "";
   while(!FileIsEnding(fileHandle))
   {
      content += FileReadString(fileHandle) + "\n";
   }
   FileClose(fileHandle);
   
   if(StringLen(content) < 10)
   {
      Print("[SmartZones] File is empty or too small");
      return;
   }
   
   payloadError = "";
   if(!ValidatePayloadHeader(content))
   {
      DeleteAllZoneObjects();
      DrawBuildStamp();
      ChartRedraw();
      return;
   }
   zonesCalcTime = ParseIsoTime(ExtractString(content, "\"calculated_at\":", 0));
   referencePrice = ExtractDouble(content, "\"reference_price\":", 0);
   payloadProducerBuild = ExtractString(content, "\"producer_build\":", 0);
   payloadId = ExtractString(content, "\"payload_id\":", 0);

   // Удаляем старые зоны
   DeleteAllZoneObjects();
   
   // Пытаемся распарсить fp_status (глобальный статус футпринта)
   string fpStatus = ExtractString(content, "\"fp_status\":", 0);
   string btnName = zonePrefix + "FP_BTN";
   if(fpStatus != "" && fpStatus != "Ready")
   {
      ObjectSetString(0, btnName, OBJPROP_TEXT, fpStatus);
      ObjectSetInteger(0, btnName, OBJPROP_COLOR, clrYellow);
   }
   else
   {
      ObjectSetString(0, btnName, OBJPROP_TEXT, "FP");
      ObjectSetInteger(0, btnName, OBJPROP_COLOR, clrWhite);
   }
   
   if(ParseZonesJSON(content))
      DrawAllZones();
   else
   {
      DeleteAllZoneObjects();
      currentZoneCount = 0;
   }
   DrawBuildStamp();

   ChartRedraw();
   Print("[SmartZones] Loaded and drawn ", currentZoneCount, " zones");
}


//+------------------------------------------------------------------+
//| Ручной парсинг JSON (MQL4 не имеет встроенного JSON-парсера)      |
//+------------------------------------------------------------------+
bool ValidatePayloadHeader(string json)
{
   string schema = ExtractString(json, "\"schema_version\":", 0);
   string kind = ExtractString(json, "\"payload_kind\":", 0);
   if(schema != "4.0" || kind != "szp_active_zones")
   {
      payloadError = "incompatible payload schema";
      Print("[SmartZones MT4] ", payloadError, ": ", schema, " / ", kind);
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
      double price = ExtractDouble(json, "\"zone_price\":", pricePos);
      double top = ExtractDouble(json, "\"zone_top\":", pricePos);
      double bottom = ExtractDouble(json, "\"zone_bottom\":", pricePos);
      int score = (int)ExtractDouble(json, "\"zone_score\":", pricePos);
      string label = ExtractString(json, "\"zone_label\":", pricePos);
      double stopPrice = ExtractDouble(json, "\"stop_price\":", pricePos);
      double stopBuffer = ExtractDouble(json, "\"stop_buffer\":", pricePos);
      int stopProbability = (int)ExtractDouble(json, "\"stop_probability\":", pricePos);
      string stopSide = ExtractString(json, "\"stop_side\":", pricePos);
      int flagPos = StringFind(json, "\"zone_fallback\": true", pricePos);
      bool fallback = (flagPos >= pricePos && (nextZone < 0 || flagPos < nextZone));
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
      ArrayResize(zoneFallback, currentZoneCount + 1);
      ArrayResize(stopPrices, currentZoneCount + 1);
      ArrayResize(stopBuffers, currentZoneCount + 1);
      ArrayResize(stopProbabilities, currentZoneCount + 1);
      ArrayResize(stopSides, currentZoneCount + 1);
      zonePrices[currentZoneCount] = price;
      zoneTops[currentZoneCount] = top;
      zoneBottoms[currentZoneCount] = bottom;
      zoneScores[currentZoneCount] = score;
      zoneLabels[currentZoneCount] = label;
      zoneFallback[currentZoneCount] = fallback;
      stopPrices[currentZoneCount] = stopPrice;
      stopBuffers[currentZoneCount] = stopBuffer;
      stopProbabilities[currentZoneCount] = stopProbability;
      stopSides[currentZoneCount] = stopSide;
      currentZoneCount++;
      if(price > referencePrice) above++;
      if(price < referencePrice) below++;
      if(nextZone < 0) break;
      searchPos = nextZone;
   }
   if(currentZoneCount != 6 || above != 3 || below != 3)
   {
      payloadError = "display contract is not 3+3";
      Print("[SmartZones MT4] ", payloadError, ": ", above, " above / ", below, " below");
      return false;
   }
   Print("[SmartZones MT4] Parsed six schema-4 zones: 3 above / 3 below");
   return true;
}


//+------------------------------------------------------------------+
//| Извлечение double из JSON строки                                  |
//+------------------------------------------------------------------+
double ExtractDouble(string json, string key, int startFrom)
{
   int keyPos = StringFind(json, key, startFrom);
   if(keyPos < 0) return 0;
   
   int valueStart = keyPos + StringLen(key);
   
   // Пропускаем пробелы
   while(valueStart < StringLen(json) && StringGetCharacter(json, valueStart) == ' ')
      valueStart++;
   
   // Ищем конец числа (запятая, }, пробел или перенос строки)
   int valueEnd = valueStart;
   while(valueEnd < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, valueEnd);
      if(ch == ',' || ch == '}' || ch == '\n' || ch == '\r')
         break;
      valueEnd++;
   }
   
   string valueStr = StringSubstr(json, valueStart, valueEnd - valueStart);
   StringTrimRight(valueStr);
   StringTrimLeft(valueStr);
   
   return StringToDouble(valueStr);
}


//+------------------------------------------------------------------+
//| Извлечение строки из JSON                                         |
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
//| Отрисовка всех зон на графике                                     |
//+------------------------------------------------------------------+
void DrawAllZones()
{
   for(int i = 0; i < currentZoneCount; i++)
   {
      DrawSingleZone(i);
   }
}


//+------------------------------------------------------------------+
//| Отрисовка одной зоны                                              |
//+------------------------------------------------------------------+
void DrawSingleZone(int index)
{
   string baseName = zonePrefix + IntegerToString(index);
   double price    = zonePrices[index];
   double top      = zoneTops[index];
   double bottom   = zoneBottoms[index];
   int    score    = zoneScores[index];
   string label    = zoneLabels[index];
   
   // Красный fallback — реальный, но менее подтверждённый уровень.
   bool  fallback = zoneFallback[index];
   color zoneColor = ZoneColorWeak;
   int   lineWidth = ZoneLineWidth;
   if(fallback)
   {
      zoneColor = ZoneColorFallback;
      lineWidth = (int)MathMax(1, ZoneLineWidth - 1);
   }
   else if(score >= 11)
   {
      zoneColor = ZoneColorStrong;
      lineWidth = ZoneLineWidth + 1;
   }
   else if(score >= 9)
   {
      zoneColor = ZoneColorMedium;
      lineWidth = ZoneLineWidth;
   }
   else
   {
      zoneColor = ZoneColorWeak;
      lineWidth = (int)MathMax(1, ZoneLineWidth - 1);
   }
   
   // ── 1. Горизонтальная линия (центр зоны) ─────────────────────────
   string lineName = baseName + "_line";
   ObjectCreate(lineName, OBJ_HLINE, 0, 0, price);
   ObjectSetInteger(0, lineName, OBJPROP_COLOR, zoneColor);
   ObjectSetInteger(0, lineName, OBJPROP_WIDTH, lineWidth);
   ObjectSetInteger(0, lineName, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, lineName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, lineName, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, lineName, OBJPROP_BACK, true);
   
   // ── 3. Текстовая подпись зоны ────────────────────────────────────
   if(ShowPriceLabels)
   {
      string textName = baseName + "_text";
      datetime labelTime = Time[0] + PeriodSeconds() * 12;
      ObjectCreate(textName, OBJ_TEXT, 0, labelTime, price);
      // Только цена зоны (без источников/скора) — как просил клиент.
      ObjectSetString(0, textName, OBJPROP_TEXT, DoubleToString(price, 2));
      ObjectSetInteger(0, textName, OBJPROP_COLOR, clrWhite);
      ObjectSetString(0, textName, OBJPROP_FONT, "Arial Bold");
      ObjectSetInteger(0, textName, OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, textName, OBJPROP_ANCHOR, ANCHOR_LEFT);
      ObjectSetInteger(0, textName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, textName, OBJPROP_HIDDEN, true);
   }

   // ── 3b. Бейдж со скором (S:11) — у правого края зоны ─────────────
   if(ShowScoreBadge)
   {
      string badgeName = baseName + "_badge";
      datetime badgeTime = Time[0] + PeriodSeconds() * 4;
      ObjectCreate(badgeName, OBJ_TEXT, 0, badgeTime, price);
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
      DrawStopCloud(baseName, index);

}


//+------------------------------------------------------------------+
//| Structural SL cloud from Python Core: green = long, red = short |
//+------------------------------------------------------------------+
void DrawStopCloud(string baseName, int index)
{
   double stopPrice = stopPrices[index];
   if(stopPrice <= 0) return;
   bool isLong = (stopSides[index] == "BELOW_SUPPORT");
   color cloudColor = isLong ? C'95,224,190' : C'239,117,132';
   double spread = MathMax(stopBuffers[index] * 0.55, Point * 12.0);
   int points = MathMax(5, MathMin(15, SLCloudPoints));
   datetime anchor = Time[0] + PeriodSeconds() * 7;
   for(int dot = 0; dot < points; dot++)
   {
      double normalized = points > 1 ? ((double)dot / (points - 1) - 0.5) : 0.0;
      double dotPrice = stopPrice + normalized * spread;
      datetime dotTime = anchor + dot * (int)MathMax(1, PeriodSeconds() / 3);
      string dotName = baseName + "_sl_cloud_" + IntegerToString(dot);
      ObjectCreate(dotName, OBJ_ARROW, 0, dotTime, dotPrice);
      ObjectSetInteger(0, dotName, OBJPROP_ARROWCODE, 159);
      ObjectSetInteger(0, dotName, OBJPROP_COLOR, cloudColor);
      ObjectSetInteger(0, dotName, OBJPROP_WIDTH, dot == points / 2 ? 2 : 1);
      ObjectSetInteger(0, dotName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, dotName, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, dotName, OBJPROP_BACK, false);
   }
   string labelName = baseName + "_sl_cloud_label";
   ObjectCreate(labelName, OBJ_TEXT, 0, anchor + (points + 1) * (int)MathMax(1, PeriodSeconds() / 3), stopPrice);
   ObjectSetString(0, labelName, OBJPROP_TEXT, (isLong ? " LONG SL cloud " : " SHORT SL cloud ") +
                   DoubleToString(stopPrice, Digits) + " ~" + IntegerToString(stopProbabilities[index]) + "%");
   ObjectSetInteger(0, labelName, OBJPROP_COLOR, cloudColor);
   ObjectSetString(0, labelName, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, labelName, OBJPROP_ANCHOR, ANCHOR_LEFT);
   ObjectSetInteger(0, labelName, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, labelName, OBJPROP_HIDDEN, true);
}


//+------------------------------------------------------------------+
//| Удаление всех объектов индикатора                                 |
//+------------------------------------------------------------------+
void DeleteAllZoneObjects()
{
   int totalObjects = ObjectsTotal();
   for(int i = totalObjects - 1; i >= 0; i--)
   {
      string name = ObjectName(i);
      // Участки набора живут своей жизнью (свой файл и своя перерисовка)
      if(StringFind(name, accumPrefix) == 0) continue;
      if(StringFind(name, buildPrefix) == 0) continue;
      if(StringFind(name, zonePrefix) == 0)
      {
         ObjectDelete(name);
      }
   }
   currentZoneCount = 0;
   ArrayResize(zonePrices, 0);
   ArrayResize(zoneTops, 0);
   ArrayResize(zoneBottoms, 0);
   ArrayResize(zoneScores, 0);
   ArrayResize(zoneLabels, 0);
   ArrayResize(zoneFallback, 0);
   ArrayResize(stopPrices, 0);
   ArrayResize(stopBuffers, 0);
   ArrayResize(stopProbabilities, 0);
   ArrayResize(stopSides, 0);
}


//+------------------------------------------------------------------+
//| Проверка алертов — цена приблизилась к зоне                       |
//+------------------------------------------------------------------+
void CheckAlerts()
{
   // Не спамим алертами чаще чем раз в 5 минут
   if(TimeCurrent() - lastAlertTime < 300)
      return;
   
   double currentPrice = Bid;
   
   for(int i = 0; i < currentZoneCount; i++)
   {
      double dist = MathAbs(currentPrice - zonePrices[i]);
      
      if(dist <= AlertDistance)
      {
         string direction = currentPrice > zonePrices[i] ? "ABOVE" : "BELOW";
         string msg = StringFormat(
            "[SmartZones] ALERT: Price %.2f is %.1f$ %s zone %.2f (S:%d)",
            currentPrice, dist, direction, zonePrices[i], zoneScores[i]
         );
         
         Alert(msg);
         Print(msg);
         
         // Push-уведомление на телефон
         if(SendNotification(msg))
            Print("[SmartZones] Push notification sent");
            
         // Записываем алерт в файл для передачи в Telegram через Python
         int fileHandle = FileOpen("tg_alerts.txt", FILE_WRITE|FILE_TXT|FILE_READ);
         if(fileHandle != INVALID_HANDLE)
         {
            FileSeek(fileHandle, 0, SEEK_END); // Дописываем в конец
            FileWriteString(fileHandle, msg + "\n");
            FileClose(fileHandle);
         }
         
         lastAlertTime = TimeCurrent();
         break;  // Один алерт за раз
      }
   }
}
//+------------------------------------------------------------------+
