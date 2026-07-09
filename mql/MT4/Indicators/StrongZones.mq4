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

//--- Настройки (Input Parameters) ------------------------------------
input int      RefreshSeconds   = 10;        // Интервал обновления (сек)
input color    ZoneColorStrong  = clrGold;   // Цвет сильных зон (Score >= 11)
input color    ZoneColorMedium  = C'200,170,60';  // Цвет средних зон (Score 9-10)
input color    ZoneColorWeak    = C'120,110,80';  // Цвет слабых зон
input int      ZoneLineWidth    = 2;         // Толщина линии зоны
input bool     ShowLabels       = true;      // Показывать цену зоны (только цена)
input bool     ShowRectangles   = true;      // Полупрозрачные прямоугольники зон
input bool     ShowScoreBadge   = false;     // Показывать бейдж со скором зоны
input bool     EnableAlerts     = true;      // Алерты при касании зоны
input double   AlertDistance    = 5.0;       // Расстояние до зоны для алерта ($)
// Имя файла с зонами — лежит в MQL4/Files или Common/Files (положит sync_zones_to_mt4.py).
input string   ZonesFilePath    = "zones_output.json";

//--- Глобальные переменные -------------------------------------------
datetime       lastFileTime     = 0;         // Время последнего изменения файла
datetime       lastAlertTime    = 0;         // Время последнего алерта
string         zonePrefix       = "SZP_";    // Префикс объектов индикатора
int            currentZoneCount = 0;         // Текущее количество зон на графике

// Храним данные зон в массивах
double         zonePrices[];
double         zoneTops[];
double         zoneBottoms[];
int            zoneScores[];
string         zoneLabels[];


//+------------------------------------------------------------------+
//| Custom indicator initialization function                          |
//+------------------------------------------------------------------+
int OnInit()
{
   // Таймер для периодического обновления
   EventSetTimer(RefreshSeconds);
   
   // Первая загрузка зон
   LoadZonesFromFile();
   
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
   
   Print("[SmartZones] Indicator initialized. Reading zones from MQL4/Files/", ZonesFilePath);
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
   // Удаляем кнопку FP
   ObjectDelete(0, zonePrefix + "FP_BTN");
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
   
   // Простой JSON парсер (MQL4 не умеет нормально парсить массивы)
   ParseZonesJSON(content);
   
   // Рисуем зоны
   DrawAllZones();
   
   ChartRedraw();
   Print("[SmartZones] Loaded and drawn ", currentZoneCount, " zones");
}


//+------------------------------------------------------------------+
//| Ручной парсинг JSON (MQL4 не имеет встроенного JSON-парсера)      |
//+------------------------------------------------------------------+
void ParseZonesJSON(string json)
{
   currentZoneCount = 0;
   
   // Ищем блоки зон: каждая зона начинается с "price":
   int searchPos = 0;
   
   while(true)
   {
      // Ищем следующий блок зоны
      int pricePos = StringFind(json, "\"price\":", searchPos);
      if(pricePos < 0) break;
      
      // Извлекаем price
      double price = ExtractDouble(json, "\"price\":", pricePos);
      double top = ExtractDouble(json, "\"top\":", pricePos);
      double bottom = ExtractDouble(json, "\"bottom\":", pricePos);
      int score = (int)ExtractDouble(json, "\"score\":", pricePos);
      string label = ExtractString(json, "\"label\":", pricePos);
      
      if(price > 0 && currentZoneCount < 20)
      {
         ArrayResize(zonePrices, currentZoneCount + 1);
         ArrayResize(zoneTops, currentZoneCount + 1);
         ArrayResize(zoneBottoms, currentZoneCount + 1);
         ArrayResize(zoneScores, currentZoneCount + 1);
         ArrayResize(zoneLabels, currentZoneCount + 1);
         
         zonePrices[currentZoneCount]  = price;
         zoneTops[currentZoneCount]    = top;
         zoneBottoms[currentZoneCount] = bottom;
         zoneScores[currentZoneCount]  = score;
         zoneLabels[currentZoneCount]  = label;
         
         currentZoneCount++;
      }
      
      searchPos = pricePos + 10;
   }
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
   
   // Определяем цвет по силе зоны
   color zoneColor = ZoneColorWeak;
   int   lineWidth = ZoneLineWidth;
   if(score >= 11)
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
   
   // ── 2. Полупрозрачный прямоугольник зоны ──────────────────
   // MQL4 не имеет альфа-канала для OBJ_RECTANGLE — имитируем
   // прозрачность явно "приглушённым" цветом + BACK=true,
   // чтобы свечи были поверх.
   if(ShowRectangles)
   {
      string rectName = baseName + "_rect";
      int barsBack    = (int)MathMin(Bars - 1, 120);
      int barsForward = 30;
      datetime timeLeft  = Time[barsBack];
      datetime timeRight = Time[0] + PeriodSeconds() * barsForward;

      // Приглушённый оттенок по силе зоны
      color rectFill;
      if(score >= 11)      rectFill = C'80,70,30';   // сильная — тёмное золото
      else if(score >= 9)  rectFill = C'55,50,30';   // средняя
      else                 rectFill = C'40,40,35';   // слабая

      ObjectCreate(rectName, OBJ_RECTANGLE, 0, timeLeft, top, timeRight, bottom);
      ObjectSetInteger(0, rectName, OBJPROP_COLOR, rectFill);
      ObjectSetInteger(0, rectName, OBJPROP_FILL, true);
      ObjectSetInteger(0, rectName, OBJPROP_BACK, true);
      ObjectSetInteger(0, rectName, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, rectName, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, rectName, OBJPROP_STYLE, STYLE_SOLID);
   }
   
   // ── 3. Текстовая подпись зоны ────────────────────────────────────
   if(ShowLabels)
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

   // Примечание: маркеры-треугольники касаний и «SL Pool»-облака убраны,
   // чтобы MT4 отображался идентично MT5 (только линия зоны, прямоугольник и
   // подпись с ценой) и не создавал «шум» на графике.
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
