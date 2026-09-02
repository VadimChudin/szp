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
// Градация как в старой версии, которая нравилась клиенту: все зоны красные,
// но чем слабее уровень — тем тусклее линия. Инпуты переименованы намеренно:
// терминал хранит значения в профиле графика, и старый ZoneColorStrong=clrGold
// оживал после обновления сборки, делая сильные зоны золотыми.
input color    ZoneColorHigh    = clrRed;            // Сильная зона (score >= 9)
input color    ZoneColorMid     = C'255,77,77';       // Средняя зона (score 7-8)
input color    ZoneColorLow     = C'255,153,153';     // Слабая / историчная (HIST)
input int      ZoneLineWidth    = 2;          // Толщина линии
// Параметр переименован из ShowLabels: терминал хранит значения инпутов в
// профиле графика, и у клиентов оставался ShowLabels=false из старой сборки —
// цены на уровнях не появлялись даже после обновления индикатора.
input bool     ShowPriceLabels  = true;       // Показывать только цену зоны
input bool     ShowRectangles   = false;       // Полупрозрачные прямоугольники зон
input bool     ShowScoreBadge   = false;      // Бейдж со скором
input bool     ShowSL           = false;      // Уровни SL Pool (по умолчанию выкл.)
input bool     ShowGradient     = false;      // Градиентная визуализация (выкл. по умолчанию)
input int      GradientLayers   = 5;          // Кол-во слоёв градиента
input bool     EnableIndicator  = true;       // Включить/выключить индикатор целиком
input bool     EnableAlerts     = true;       // Алерты при касании зоны
input double   AlertDistance    = 5.0;        // Расстояние для алерта ($)
input bool     ShowZakrep       = true;       // Пометка/алерт «ЗАКРЕП за зоной» (H1 закрытие и удержание за уровнем)
// Раскраска зон по реакции удалена намеренно: зона BOUNCE подсвечивалась clrLimeGreen, и при
// каждом пересчёте реакция могла переключиться BOUNCE <-> NONE — линия мигала красным/зелёным.
// Клиенту нужны ВСЕ зоны одним красным цветом, сила уровня передаётся только толщиной линии.
// Инпут переименован (был ShowReaction): терминал хранит значения инпутов в профиле графика,
// и у клиентов со старой сборкой ShowReaction=true оживал после обновления.
input bool     ShowReactionTag  = false;      // Текстовая метка реакции у цены (цвет линии НЕ меняет)
input bool     LabelAboveLine   = true;       // Подпись цены НАД линией зоны (не поверх неё)
input double   LabelOffsetUSD   = 0.0;        // Доп. отступ подписи от линии ($)
input bool     AutoFitChart     = true;       // Автоподгон шкалы под все 6 зон
input double   FitMarginPct     = 3.0;        // Запас шкалы сверху/снизу (%)
input bool     ShowAccumulation = false;     // Набор позиции крупным участником
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
bool           zoneFallback[];
string         zoneReaction[];
string         zoneReactionDir[];

// ── Состояние для защиты от мерцания ──────────────────────────────────────────
// Раньше OnTimer каждые RefreshSeconds делал DeleteAllZoneObjects() + DrawAllZones():
// объекты уничтожались и создавались заново, и график заметно мигал каждые 10 секунд.
// Теперь перерисовка идёт только когда реально поменялось содержимое JSON или сдвинулся
// бар привязки подписей, а сами объекты обновляются на месте (ObjectMove / ObjectSet*).
string         lastZonesRaw     = "";  // содержимое zones_output.json на прошлой отрисовке
string         lastAccumRaw     = "";  // содержимое accumulation_output.json
datetime       lastAnchorBar    = 0;   // бар, к которому привязаны текстовые подписи
int            drawnZoneCount   = 0;   // сколько зон реально отрисовано (для чистки хвостов)
bool           zoneSetChanged   = false;

//+------------------------------------------------------------------+
//| Идемпотентные операции над объектами.                            |
//| Ключевая идея анти-мерцания: не удалять и создавать заново, а     |
//| менять свойство только если оно действительно другое. Любой       |
//| ObjectSet* помечает график «грязным», поэтому лишние вызовы —     |
//| это лишние перерисовки.                                          |
//+------------------------------------------------------------------+
bool EnsureObject(string name, ENUM_OBJECT type, datetime t1, double p1)
{
   if(ObjectFind(0, name) >= 0)
      return false;                       // объект уже на графике — не пересоздаём
   ObjectCreate(0, name, type, 0, t1, p1);
   return true;
}

void SetIntIfChanged(string name, ENUM_OBJECT_PROPERTY_INTEGER prop, long value)
{
   if(ObjectGetInteger(0, name, prop) != value)
      ObjectSetInteger(0, name, prop, value);
}

void SetStrIfChanged(string name, ENUM_OBJECT_PROPERTY_STRING prop, string value)
{
   if(ObjectGetString(0, name, prop) != value)
      ObjectSetString(0, name, prop, value);
}

void MovePointIfChanged(string name, int point, datetime t, double price)
{
   datetime curT = (datetime)ObjectGetInteger(0, name, OBJPROP_TIME, point);
   double   curP = ObjectGetDouble(0, name, OBJPROP_PRICE, point);
   if(curT != t || MathAbs(curP - price) > 1e-8)
      ObjectMove(0, name, point, t, price);
}

//+------------------------------------------------------------------+
//| Бар, к которому крепятся текстовые подписи. Меняется только при  |
//| появлении новой свечи — тогда подписи сдвигаются (ObjectMove),   |
//| а не пересоздаются.                                              |
//+------------------------------------------------------------------+
datetime AnchorBar()
{
   return iTime(_Symbol, PERIOD_CURRENT, 0);
}


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
   // Ставим свойства только при фактическом изменении: этот штамп вызывается
   // каждые RefreshSeconds, а безусловный ObjectSet* помечает график «грязным».
   SetIntIfChanged(name, OBJPROP_COLOR, clr);
   SetStrIfChanged(name, OBJPROP_TEXT, text);
}

//+------------------------------------------------------------------+
int OnInit()
{
   // Чистим объекты сразу при инициализации (в т.ч. при смене ТФ). Иначе
   // подписи/объекты, сохранённые в профиле графика от прежней версии
   // индикатора, «мигают» до первой успешной загрузки JSON.
   DeleteAllZoneObjects();
   DeleteAccumulationObjects();
   // Сбрасываем кэш содержимого, иначе после смены ТФ объекты удалены,
   // а индикатор считает, что «данные те же», и график остаётся пустым.
   lastZonesRaw  = "";
   lastAccumRaw  = "";
   lastAnchorBar = 0;
   if(!EnableIndicator)
   {
      Print("[SmartZones MT5] Disabled (EnableIndicator=false)");
      return(INIT_SUCCEEDED);
   }
   EventSetTimer(RefreshSeconds);
   LoadZonesFromFile();
   AutoFitChartToZones();
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
   ChartSetInteger(0, CHART_SCALEFIX, false); // отпускаем шкалу
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

//+------------------------------------------------------------------+
//| Автоподгон шкалы графика под активные зоны.                        |
//| Без этого зоны ниже цены оставались за пределами видимой области  |
//| и клиент видел «все уровни сверху», хотя они были посчитаны.       |
//+------------------------------------------------------------------+
void AutoFitChartToZones()
{
   if(!AutoFitChart || currentZoneCount <= 0) return;
   // Раньше шкала переустанавливалась каждые RefreshSeconds, и график «дёргался»
   // даже когда набор зон не менялся. Теперь подгоняем только при смене набора.
   if(!zoneSetChanged) return;
   double lo = zonePrices[0], hi = zonePrices[0];
   for(int i = 1; i < currentZoneCount; i++)
   {
      if(zonePrices[i] < lo) lo = zonePrices[i];
      if(zonePrices[i] > hi) hi = zonePrices[i];
   }
   // Текущая цена обязана оставаться в кадре
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(bid > 0)
   {
      if(bid < lo) lo = bid;
      if(bid > hi) hi = bid;
   }
   double margin = (hi - lo) * FitMarginPct / 100.0;
   if(margin < 1.0) margin = 1.0;
   ChartSetDouble(0, CHART_PRICE_MIN, lo - margin);
   ChartSetDouble(0, CHART_PRICE_MAX, hi + margin);
   ChartSetInteger(0, CHART_SCALEFIX, true);
}

void OnTimer()
{
   LoadZonesFromFile();
   AutoFitChartToZones();
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

   // Участки набора тоже пересоздавались на каждом тике таймера и мигали.
   // Пересобираем их только при изменении файла.
   if(content == lastAccumRaw) return;
   lastAccumRaw = content;

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

   datetime anchor       = AnchorBar();
   bool     dataChanged  = (content != lastZonesRaw);
   bool     anchorMoved  = (anchor  != lastAnchorBar);

   // Главный фикс мерцания: если ни JSON, ни бар привязки не изменились —
   // на графике менять нечего. Раньше здесь безусловно выполнялось
   // DeleteAllZoneObjects() + DrawAllZones(), то есть все линии и подписи
   // уничтожались и создавались заново каждые RefreshSeconds секунд.
   if(!dataChanged && !anchorMoved)
   {
      zoneSetChanged = false;
      DrawBuildStamp();   // в углу обновляется только возраст данных
      return;
   }

   lastZonesRaw   = content;
   lastAnchorBar  = anchor;
   zoneSetChanged = dataChanged;

   if(dataChanged)
   {
      ParseZonesJSON(content);
      zonesCalcTime = ParseIsoTime(ExtractString(content, "\"calculated_at\":", 0));
   }

   DrawAllZones();                            // обновление на месте, без пересоздания
   DeleteStaleZoneObjects(currentZoneCount);  // убираем хвосты от прошлого набора зон
   DrawBuildStamp();
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Удаляет объекты зон с индексом >= keepCount.                     |
//| Нужно только когда зон стало меньше: живые зоны не трогаем, поэтому|
//| мерцания нет.                                                    |
//+------------------------------------------------------------------+
void DeleteStaleZoneObjects(int keepCount)
{
   for(int i = ObjectsTotal(0) - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i);
      if(StringFind(name, accumPrefix) == 0) continue;
      if(StringFind(name, buildPrefix) == 0) continue;
      if(StringFind(name, zonePrefix) != 0)  continue;

      // Имя выглядит как SZP_<index>_<suffix>. Достаём index.
      string tail = StringSubstr(name, StringLen(zonePrefix));
      int    sep  = StringFind(tail, "_");
      if(sep <= 0) continue;
      string idxStr = StringSubstr(tail, 0, sep);
      int    idx    = (int)StringToInteger(idxStr);
      if(IntegerToString(idx) != idxStr) continue;   // не наш служебный объект

      if(idx >= keepCount)
         ObjectDelete(0, name);
   }
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
                        StringFind(json, "\"has_big_player\": true", pricePos) < pricePos + 700);
      bool   fallback = (StringFind(json, "\"is_fallback\": true", pricePos) > 0 &&
                         StringFind(json, "\"is_fallback\": true", pricePos) < pricePos + 900);

      // Реакция цены на зону: парсим внутри блока "reaction":{...} этой зоны,
      // чтобы не зацепить ключи соседних объектов.
      string reaction = "";
      string reactionDir = "";
      int reactionPos = StringFind(json, "\"reaction\":", pricePos);
      if(reactionPos > 0 && reactionPos < pricePos + 1200)
      {
         reaction    = ExtractString(json, "\"type\":", reactionPos);
         reactionDir = ExtractString(json, "\"direction\":", reactionPos);
      }

      // Hard UI guard: never draw more than six active levels.
      if(price > 0 && currentZoneCount < 6)
      {
         ArrayResize(zonePrices, currentZoneCount + 1);
         ArrayResize(zoneTops, currentZoneCount + 1);
         ArrayResize(zoneBottoms, currentZoneCount + 1);
         ArrayResize(zoneScores, currentZoneCount + 1);
         ArrayResize(zoneLabels, currentZoneCount + 1);
         ArrayResize(zoneBigPlayer, currentZoneCount + 1);
         ArrayResize(zoneFallback, currentZoneCount + 1);
         ArrayResize(zoneReaction, currentZoneCount + 1);
         ArrayResize(zoneReactionDir, currentZoneCount + 1);

         zonePrices[currentZoneCount]    = price;
         zoneTops[currentZoneCount]      = top;
         zoneBottoms[currentZoneCount]   = bottom;
         zoneScores[currentZoneCount]    = score;
         zoneLabels[currentZoneCount]    = label;
         zoneBigPlayer[currentZoneCount] = bp;
         zoneFallback[currentZoneCount]  = fallback;
         zoneReaction[currentZoneCount]    = reaction;
         zoneReactionDir[currentZoneCount] = reactionDir;

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

   // Клиент просил все зоны ОДНИМ красным цветом. Сила уровня теперь передаётся
   // только толщиной линии — цветовой иерархии (золото/средний/слабый) больше нет.
   bool  fallback = zoneFallback[index];
   string reaction    = zoneReaction[index];
   string reactionDir = zoneReactionDir[index];
   // Цвет по силе уровня (как в старой версии): ярко-красный у сильных,
   // тусклее у слабых и историчных (HIST приходит с пониженным score).
   // Раскраска по РЕАКЦИИ удалена — именно она давала мигание красным/зелёным.
   color zoneColor = score >= 9 ? ZoneColorHigh
                   : score >= 7 ? ZoneColorMid
                                : ZoneColorLow;
   if(fallback) zoneColor = ZoneColorLow;
   int   lineWidth = score >= 11 ? ZoneLineWidth + 1
                   : score >= 9  ? ZoneLineWidth
                                 : MathMax(1, ZoneLineWidth - 1);
   if(fallback) lineWidth = MathMax(1, ZoneLineWidth - 1);

   // ── 1. Горизонтальная линия ───────────────────────────────────────
   string lineName = baseName + "_line";
   EnsureObject(lineName, OBJ_HLINE, 0, price);
   MovePointIfChanged(lineName, 0, 0, price);
   SetIntIfChanged(lineName, OBJPROP_COLOR, zoneColor);
   SetIntIfChanged(lineName, OBJPROP_WIDTH, lineWidth);
   SetIntIfChanged(lineName, OBJPROP_STYLE, STYLE_SOLID);
   SetIntIfChanged(lineName, OBJPROP_SELECTABLE, false);
   SetIntIfChanged(lineName, OBJPROP_HIDDEN, true);
   SetIntIfChanged(lineName, OBJPROP_BACK, true);

   // ── 3. Текстовая подпись ──────────────────────────────────────────
   string textName = baseName + "_text";
   if(ShowPriceLabels)
   {
      // Подпись ставим НАД линией: ANCHOR_LEFT_LOWER прижимает низ текста к цене
      // зоны, поэтому цифры больше не лежат поверх самой линии.
      datetime textTime  = AnchorBar() - PeriodSeconds() * 10;
      double   textPrice = price + (LabelAboveLine ? LabelOffsetUSD : -LabelOffsetUSD);

      EnsureObject(textName, OBJ_TEXT, textTime, textPrice);
      MovePointIfChanged(textName, 0, textTime, textPrice);

      string rtag = "";
      if(ShowReactionTag && reaction != "" && reaction != "NONE")
      {
         string arrow = reactionDir == "UP" ? " ^" : reactionDir == "DOWN" ? " v" : "";
         rtag = "  [" + reaction + arrow + "]";
      }
      SetStrIfChanged(textName, OBJPROP_TEXT, DoubleToString(price, 2) + rtag);
      SetIntIfChanged(textName, OBJPROP_COLOR, clrWhite);
      SetStrIfChanged(textName, OBJPROP_FONT, "Arial Bold");
      SetIntIfChanged(textName, OBJPROP_FONTSIZE, 9);
      SetIntIfChanged(textName, OBJPROP_ANCHOR,
                      LabelAboveLine ? ANCHOR_LEFT_LOWER : ANCHOR_LEFT_UPPER);
      SetIntIfChanged(textName, OBJPROP_SELECTABLE, false);
      SetIntIfChanged(textName, OBJPROP_HIDDEN, true);
   }
   else if(ObjectFind(0, textName) >= 0)
      ObjectDelete(0, textName);

   // ── 3b. Бейдж со скором зоны ──────────────────────────────────────
   // ── 3z. Пометка «ЗАКРЕП за зоной» (H1 закрытие и удержание за уровнем) ──
   string zkName = baseName + "_zakrep";
   if(ShowZakrep && reaction == "BREAKOUT")
   {
      datetime zkTime = AnchorBar() + PeriodSeconds() * 8;
      string zkArrow = reactionDir == "UP" ? "^" : reactionDir == "DOWN" ? "v" : "";
      EnsureObject(zkName, OBJ_TEXT, zkTime, price);
      MovePointIfChanged(zkName, 0, zkTime, price);
      SetStrIfChanged(zkName, OBJPROP_TEXT, "ZAKREP " + zkArrow);
      SetIntIfChanged(zkName, OBJPROP_COLOR, clrYellow);
      SetStrIfChanged(zkName, OBJPROP_FONT, "Arial Bold");
      SetIntIfChanged(zkName, OBJPROP_FONTSIZE, 10);
      SetIntIfChanged(zkName, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
      SetIntIfChanged(zkName, OBJPROP_SELECTABLE, false);
      SetIntIfChanged(zkName, OBJPROP_HIDDEN, true);
   }
   else if(ObjectFind(0, zkName) >= 0)
      ObjectDelete(0, zkName);

   string badgeName = baseName + "_badge";
   if(ShowScoreBadge)
   {
      datetime badgeTime = AnchorBar() + PeriodSeconds() * 4;
      EnsureObject(badgeName, OBJ_TEXT, badgeTime, price);
      MovePointIfChanged(badgeName, 0, badgeTime, price);
      SetStrIfChanged(badgeName, OBJPROP_TEXT, " S:" + IntegerToString(score) + " ");
      SetIntIfChanged(badgeName, OBJPROP_COLOR, zoneColor);
      SetStrIfChanged(badgeName, OBJPROP_FONT, "Consolas");
      SetIntIfChanged(badgeName, OBJPROP_FONTSIZE, 9);
      SetIntIfChanged(badgeName, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
      SetIntIfChanged(badgeName, OBJPROP_SELECTABLE, false);
      SetIntIfChanged(badgeName, OBJPROP_HIDDEN, true);
   }
   else if(ObjectFind(0, badgeName) >= 0)
      ObjectDelete(0, badgeName);

   // ── 4. Structural SL Pool ─────────────────────────────────────────
   // SL is placed outside the zone using a bounded ATR buffer and the nearest
   // recent swing. It is a possible liquidity/stop level, not a trade signal.
   // Клиент просил «только зоны, ничего лишнего»: ранее этот блок выполнялся
   // безусловно для каждой зоны и добавлял на график 6 пунктиров + 6 подписей.
   if(!ShowSL)
   {
      // Инпут выключили на живом графике — снимаем ранее нарисованные объекты SL,
      // иначе они висят до перезапуска индикатора.
      if(ObjectFind(0, baseName + "_sl_line")  >= 0) ObjectDelete(0, baseName + "_sl_line");
      if(ObjectFind(0, baseName + "_sl_label") >= 0) ObjectDelete(0, baseName + "_sl_label");
      return;
   }

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
   color slColor = C'189,167,255'; // violet SL; red is reserved for fallback zones
   string slLineName = baseName + "_sl_line";
   EnsureObject(slLineName, OBJ_HLINE, 0, slLevel);
   MovePointIfChanged(slLineName, 0, 0, slLevel);
   SetIntIfChanged(slLineName, OBJPROP_COLOR, slColor);
   SetIntIfChanged(slLineName, OBJPROP_WIDTH, 1);
   SetIntIfChanged(slLineName, OBJPROP_STYLE, STYLE_DASH);
   SetIntIfChanged(slLineName, OBJPROP_SELECTABLE, false);
   SetIntIfChanged(slLineName, OBJPROP_HIDDEN, true);
   SetIntIfChanged(slLineName, OBJPROP_BACK, true);

   string slTextName = baseName + "_sl_label";
   datetime slTextTime = AnchorBar() + PeriodSeconds() * 80;
   EnsureObject(slTextName, OBJ_TEXT, slTextTime, slLevel);
   MovePointIfChanged(slTextName, 0, slTextTime, slLevel);
   SetStrIfChanged(slTextName, OBJPROP_TEXT, " SL Pool " + DoubleToString(slLevel, _Digits) + " ~" + IntegerToString(slProb) + "%");
   SetIntIfChanged(slTextName, OBJPROP_COLOR, slColor);
   SetStrIfChanged(slTextName, OBJPROP_FONT, "Consolas");
   SetIntIfChanged(slTextName, OBJPROP_FONTSIZE, 8);
   SetIntIfChanged(slTextName, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
   SetIntIfChanged(slTextName, OBJPROP_SELECTABLE, false);
   SetIntIfChanged(slTextName, OBJPROP_HIDDEN, true);

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

      if(ObjectFind(0, rectName) < 0)
         ObjectCreate(0, rectName, OBJ_RECTANGLE, 0, timeLeft, layerTop, timeRight, layerBottom);
      MovePointIfChanged(rectName, 0, timeLeft,  layerTop);
      MovePointIfChanged(rectName, 1, timeRight, layerBottom);
      SetIntIfChanged(rectName, OBJPROP_COLOR, gradColors[i]);
      SetIntIfChanged(rectName, OBJPROP_FILL, true);
      SetIntIfChanged(rectName, OBJPROP_BACK, true);
      SetIntIfChanged(rectName, OBJPROP_SELECTABLE, false);
      SetIntIfChanged(rectName, OBJPROP_HIDDEN, true);
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
   ArrayFree(zoneFallback);
   ArrayFree(zoneReaction);
   ArrayFree(zoneReactionDir);
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
         string rx = zoneReaction[i];
         string rxinfo = (rx != "" && rx != "NONE")
                         ? " | reaction: " + rx + (zoneReactionDir[i] != "" ? " " + zoneReactionDir[i] : "")
                         : "";
         string msg = StringFormat(
            "[SmartZones] Price %.2f is %.1f$ %s zone %.2f (S:%d)%s",
            currentPrice, dist, direction, zonePrices[i], zoneScores[i], rxinfo
         );

         Alert(msg);
         SendNotification(msg);
         lastAlertTime = TimeCurrent();
         break;
      }
   }
}
//+------------------------------------------------------------------+
