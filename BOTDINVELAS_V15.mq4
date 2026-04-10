//+------------------------------------------------------------------+
//|  BOTDINVELAS_V15.mq4                                             |
//|  Indicador de sinais para MetaTrader 4 — Motor V15 completo     |
//|  Tradução fiel do BOTDINVELAS M5/M15 v16 (Python → MQL4)        |
//|                                                                  |
//|  Arquitetura:                                                    |
//|    • Setas CALL (verde ↑) / PUT (vermelho ↓) no gráfico         |
//|    • Painel informativo: score breakdown + filtros em tempo real |
//|    • Alertas: popup, som e push notification configuráveis       |
//|    • Exportação CSV para integração com bot executor Python      |
//|                                                                  |
//|  Score composto máx ~135 pts:                                   |
//|    RSI(0-25) + BB(0-25) + Wick(0-25) + Impulso(0-25)           |
//|    + Keltner(0-20 bônus) + Engolfo/Pinça(0-20 bônus)           |
//|                                                                  |
//|  Funciona em M5 e M15 (detecta automaticamente o timeframe)     |
//+------------------------------------------------------------------+
#property copyright   "BOTDINVELAS"
#property link        "https://github.com/edsmendanha/BOTDINVELASM1M5"
#property version     "15.0"
#property strict
#property description "Motor V15 — RSI+BB+Wick+Impulso+Keltner+Engolfo | Filtros 2-de-4"

#property indicator_chart_window
#property indicator_buffers 4
#property indicator_color1  clrLime     // CALL — seta verde para cima
#property indicator_color2  clrRed      // PUT  — seta vermelha para baixo
#property indicator_color3  clrNONE     // CallScoreBuffer (oculto)
#property indicator_color4  clrNONE     // PutScoreBuffer  (oculto)
#property indicator_width1  2
#property indicator_width2  2

// =======================================================================
// INPUTS — Parâmetros configuráveis (todos os thresholds e flags)
// =======================================================================

//--- Score mínimo V15
input int            InpScoreMinM5        = 58;       // Score mínimo para sinal M5
input int            InpScoreMinM15       = 60;       // Score mínimo para sinal M15
input int            InpScoreGapMin       = 1;        // Gap mínimo call-put para confirmar direção

//--- RSI
input int            InpRSIPeriod         = 14;       // Período RSI
input int            InpRSIOversold       = 30;       // RSI ≤ este valor = oversold → CALL 25pts
input int            InpRSIOverbought     = 70;       // RSI ≥ este valor = overbought → PUT 25pts

//--- Bollinger Bands
input int            InpBBPeriod          = 20;       // Período Bollinger Bands
input double         InpBBStd             = 2.0;      // Multiplicador desvio padrão
input double         InpBBProximity       = 0.25;     // Fração da largura da banda = "próximo do extremo"

//--- Canal Keltner (bônus 0-20 pts)
input bool           InpKeltnerEnable     = true;     // Habilitar bônus Canal Keltner
input int            InpKeltnerPeriod     = 20;       // Período EMA/ATR Keltner
input double         InpKeltnerShift      = 1.5;      // Multiplicador ATR Keltner

//--- Impulso e Contexto (0-25 pts)
input int            InpImpulseLookback   = 5;        // Lookback impulso (velas)
input int            InpContextLookback   = 12;       // Lookback contexto tendência (velas)
input double         InpTrendThreshold    = 0.0008;   // Limiar para detectar downtrend/uptrend
input double         InpImpulseThreshold  = 0.0006;   // Limiar mínimo de impulso para pontuar
input double         InpImpulseMultiplier = 8000.0;   // Fator de conversão impulso → pontos
input double         InpWickRatio         = 0.45;     // Wick mínimo (wick/range da vela)

//--- Filtro ATR (regime 2-de-4)
input bool           InpEnableATR         = true;     // Habilitar filtro ATR
input int            InpATRPeriod         = 14;       // Período ATR
input double         InpATRMinM5          = 0.000020; // ATR/close mínimo para M5
input double         InpATRMinM15         = 0.000060; // ATR/close mínimo para M15
input double         InpATRAdaptFactor    = 0.45;     // Fator adaptativo (mediana das últimas N leituras)
input int            InpATRQueueSize      = 30;       // Tamanho da fila histórica ATR adaptativo
input double         InpATRMaxThrM5       = 0.00150;  // Cap máximo do threshold adaptativo M5
input double         InpATRMaxThrM15      = 0.00300;  // Cap máximo do threshold adaptativo M15

//--- Filtro ADX (regime 2-de-4)
input bool           InpEnableADX         = true;     // Habilitar filtro ADX
input int            InpADXPeriod         = 14;       // Período ADX
input double         InpADXMinM5          = 8.0;      // ADX mínimo para M5
input double         InpADXMinM15         = 12.0;     // ADX mínimo para M15

//--- Filtro Largura BB (regime 2-de-4)
input bool           InpEnableBBW         = true;     // Habilitar filtro largura BB
input double         InpBBWidthMinM5      = 0.00045;  // (upper-lower)/middle mínimo M5
input double         InpBBWidthMinM15     = 0.00120;  // (upper-lower)/middle mínimo M15

//--- Filtro Slope EMA (regime 2-de-4)
input bool           InpEnableSlope       = true;     // Habilitar filtro slope EMA
input int            InpSlopeEMAPeriod    = 21;       // Período EMA para cálculo de slope
input int            InpSlopeLookback     = 8;        // Lookback slope: |EMA[now]-EMA[now-N]|/close
input double         InpSlopeMinM5        = 0.000060; // Slope normalizado mínimo M5
input double         InpSlopeMinM15       = 0.000150; // Slope normalizado mínimo M15

//--- Filtros estruturais
input bool           InpEnableM5Extreme   = true;     // Habilitar filtro extremo M5
input int            InpM5ExtremeCandles  = 20;       // Janela filtro extremo M5 (velas)
input double         InpM5ExtremeFrac     = 0.20;     // Fração do range aceita (20% = extremo)
input bool           InpEnableM15Struct   = true;     // Habilitar filtro estrutural M15
input int            InpM15StructCandles  = 5;        // Janela filtro estrutural M15 (velas)

//--- Pivôs / Fractais (informativo)
input bool           InpEnablePivots      = true;     // Exibir análise de proximidade a pivôs
input int            InpPivotLeft         = 2;        // Janela esquerda do fractal (velas)
input int            InpPivotRight        = 2;        // Janela direita do fractal (velas)
input double         InpPivotProxPct      = 0.002;    // Proximidade pivô (0.2% do preço)

//--- Fallback padrões de vela
input int            InpFallbackMinM15    = 38;      // Score V15 mínimo para fallback em M15

//--- Confirmação opcional
input bool           InpConfirmEnable     = true;     // Confirmar direção na vela em formação
// (M5: preço atual vs fechamento candidata; M15: + buffer ATR*0.1)

//--- Janela de entrada (alertas/CSV apenas dentro da janela)
input int            InpEntryWindowM5     = 45;       // Janela de entrada M5 (segundos)
input int            InpEntryWindowM15    = 60;       // Janela de entrada M15 (segundos)

//--- Alertas
input bool           InpAlertPopup        = true;     // Alerta popup ao detectar sinal
input bool           InpAlertSound        = true;     // Alerta sonoro (arquivo .wav)
input string         InpSoundFile         = "alert.wav"; // Arquivo de som (pasta Sounds)
input bool           InpPushNotif         = false;    // Push notification para celular

//--- Exportação CSV
input bool           InpExportCSV         = true;     // Exportar sinais para arquivo CSV
input string         InpCSVPath           = "signals_botdinvelas.csv"; // Caminho do arquivo CSV

// =======================================================================
// BUFFERS DE INDICADOR
// =======================================================================
double BuyArrow[];        // Setas de CALL (verde ↑, Wingdings 233)
double SellArrow[];       // Setas de PUT  (vermelho ↓, Wingdings 234)
double CallScoreBuffer[]; // Score CALL (buffer oculto, para data window)
double PutScoreBuffer[];  // Score PUT  (buffer oculto, para data window)

// =======================================================================
// VARIÁVEIS GLOBAIS DE ESTADO
// =======================================================================
int      g_tf            = 0;    // Timeframe detectado: 5 (M5) ou 15 (M15)
datetime g_lastBarTime   = 0;    // Open-time da última barra processada

// Fila circular para threshold adaptativo do ATR (últimas N leituras de ratio)
double g_atrQueue5[30];          // Fila ATR M5 (maxlen = InpATRQueueSize)
double g_atrQueue15[30];         // Fila ATR M15
int    g_atrQ5Idx    = 0;        // Próximo índice a escrever na fila M5
int    g_atrQ5Cnt    = 0;        // Número de elementos válidos na fila M5
int    g_atrQ15Idx   = 0;
int    g_atrQ15Cnt   = 0;

// Informações do último sinal (para painel e CSV)
datetime g_lastSigTime  = 0;
string   g_lastSigDir   = "";
int      g_lastSigScore = 0;
int      g_lastCallScr  = 0;
int      g_lastPutScr   = 0;
string   g_lastSigPat   = "";
int      g_lastRsiPts   = 0;
int      g_lastBbPts    = 0;
int      g_lastWickPts  = 0;
int      g_lastImpPts   = 0;
int      g_lastKelPts   = 0;
int      g_lastEngPts   = 0;
bool     g_lastAtrOk    = false;
bool     g_lastAdxOk    = false;
bool     g_lastBbwOk    = false;
bool     g_lastSlopeOk  = false;
double   g_lastPivDist  = 1.0;
bool     g_csvHdrWritten = false;

// Nomes dos objetos do painel
#define PANEL_PREFIX "BDV_"
#define MIN_BARS     55         // Mínimo de barras históricas para funcionamento

// =======================================================================
// OnInit — Inicialização dos buffers e painel
// =======================================================================
int OnInit()
  {
   // Verifica se o timeframe é suportado
   g_tf = (int)Period();
   if(g_tf != 5 && g_tf != 15)
     {
      Alert("BOTDINVELAS V15: Indicador apenas para M5 e M15!");
      return(INIT_FAILED);
     }

   // Configura buffer CALL (setas para cima)
   SetIndexBuffer(0, BuyArrow);
   SetIndexStyle(0, DRAW_ARROW);
   SetIndexArrow(0, 233);       // Wingdings 233 = seta para cima
   SetIndexLabel(0, "CALL V15");
   SetIndexEmptyValue(0, EMPTY_VALUE);

   // Configura buffer PUT (setas para baixo)
   SetIndexBuffer(1, SellArrow);
   SetIndexStyle(1, DRAW_ARROW);
   SetIndexArrow(1, 234);       // Wingdings 234 = seta para baixo
   SetIndexLabel(1, "PUT V15");
   SetIndexEmptyValue(1, EMPTY_VALUE);

   // Buffers auxiliares de score (ocultos na janela de dados)
   SetIndexBuffer(2, CallScoreBuffer);
   SetIndexStyle(2, DRAW_NONE);
   SetIndexLabel(2, "CallScore");
   SetIndexEmptyValue(2, 0.0);

   SetIndexBuffer(3, PutScoreBuffer);
   SetIndexStyle(3, DRAW_NONE);
   SetIndexLabel(3, "PutScore");
   SetIndexEmptyValue(3, 0.0);

   // Inicializa filas ATR
   // Nota: arrays fixos em tamanho 30; InpATRQueueSize é limitado a 30 em UpdateATRQueue
   // (via MathMin), garantindo que nunca ocorra escrita fora dos limites.
   ArrayInitialize(g_atrQueue5,  0.0);
   ArrayInitialize(g_atrQueue15, 0.0);
   g_atrQ5Idx = g_atrQ5Cnt = 0;
   g_atrQ15Idx = g_atrQ15Cnt = 0;

   g_lastBarTime = 0;
   g_lastSigTime = 0;
   g_lastSigDir  = "";
   g_csvHdrWritten = false;

   // Cria painel informativo
   CreatePanel();

   IndicatorShortName("BOTDINVELAS V15 [" + IntegerToString(g_tf) + "m]");
   return(INIT_SUCCEEDED);
  }

// =======================================================================
// OnDeinit — Remove objetos do painel ao fechar o indicador
// =======================================================================
void OnDeinit(const int reason)
  {
   // Remove todos os objetos do painel (prefixo BDV_)
   ObjectsDeleteAll(0, PANEL_PREFIX);
  }

// =======================================================================
// OnCalculate — Loop principal de cálculo
// =======================================================================
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double   &open[],
                const double   &high[],
                const double   &low[],
                const double   &close[],
                const long     &tick_volume[],
                const long     &volume[],
                const int      &spread[])
  {
   // Aguarda barras suficientes
   if(rates_total < MIN_BARS)
      return(0);

   // Determina o intervalo de barras a processar
   // Usando global arrays (índice 0 = barra atual, 1 = última fechada, ...)
   int startBar;
   if(prev_calculated <= 0)
      startBar = rates_total - MIN_BARS; // primeiro cálculo: processa barras históricas
   else
      startBar = rates_total - prev_calculated; // apenas novas barras

   if(startBar < 1)
      startBar = 1;

   // Itera de barras mais antigas para as mais recentes.
   // Arrays globais em MQL4: índice 0 = barra atual (formando),
   // 1 = última barra fechada, startBar = barra mais antiga não calculada.
   for(int bar = startBar; bar >= 1; bar--)
     {
      ProcessBar(bar);
     }

   UpdatePanel();

   return(rates_total);
  }

// =======================================================================
// ProcessBar — Processa uma barra específica para detecção de sinal
// bar=1 → última barra fechada; bar=2 → anterior; etc.
// =======================================================================
void ProcessBar(int bar)
  {
   // Garante dados suficientes para o índice solicitado
   int totalBars = iBars(NULL, 0);
   if(bar + InpM5ExtremeCandles + 5 >= totalBars)
      return;

   // ── Componente RSI (0-25 pts) ──────────────────────────────────────
   int rsiPts = 0, rsiDir = 0;
   CalcRSIScore(bar, rsiPts, rsiDir);

   // ── Componente BB (0-25 pts) ───────────────────────────────────────
   int bbPts = 0, bbDir = 0;
   CalcBBScore(bar, bbPts, bbDir);

   // ── Componente Wick (0-25 pts) ────────────────────────────────────
   int wickPts = 0, wickDir = 0;
   CalcWickScore(bar, wickPts, wickDir);

   // ── Componente Impulso + Contexto (0-25 pts) ──────────────────────
   int impPts = 0, impDir = 0;
   CalcImpulseScore(bar, impPts, impDir);

   // ── Componente Keltner (0-20 pts bônus) ───────────────────────────
   int kelPts = 0, kelDir = 0;
   CalcKeltnerScore(bar, kelPts, kelDir);

   // ── Componente Engolfo / Pinça (0-20 pts bônus) ───────────────────
   int engPts = 0, engDir = 0;
   CalcEngulfScore(bar, engPts, engDir);

   // ── Soma dos scores por direção ────────────────────────────────────
   int callScore = 0, putScore = 0;
   if(rsiDir  ==  1) callScore += rsiPts;
   if(rsiDir  == -1) putScore  += rsiPts;
   if(bbDir   ==  1) callScore += bbPts;
   if(bbDir   == -1) putScore  += bbPts;
   if(wickDir ==  1) callScore += wickPts;
   if(wickDir == -1) putScore  += wickPts;
   if(impDir  ==  1) callScore += impPts;
   if(impDir  == -1) putScore  += impPts;
   if(kelDir  ==  1) callScore += kelPts;
   if(kelDir  == -1) putScore  += kelPts;
   if(engDir  ==  1) callScore += engPts;
   if(engDir  == -1) putScore  += engPts;

   // Armazena scores nos buffers auxiliares
   CallScoreBuffer[bar] = callScore;
   PutScoreBuffer[bar]  = putScore;

   // ── Filtros de regime (2-de-4) ────────────────────────────────────
   bool atrOk, adxOk, bbwOk, slopeOk;
   bool regimeOk = PassesRegimeFilters(bar, atrOk, adxOk, bbwOk, slopeOk);

   // ── Score mínimo por timeframe ────────────────────────────────────
   int scoreMin = (g_tf == 5) ? InpScoreMinM5 : InpScoreMinM15;

   // ── Verifica sinal CALL ────────────────────────────────────────────
   if(callScore >= scoreMin && (callScore - putScore) >= InpScoreGapMin && regimeOk)
     {
      if(CheckStructuralFilter(bar, 1))   // 1 = CALL
        {
         // Verifica pivô para informação
         double pivDist = FindPivotDist(bar, 1);

         // Emite sinal
         EmitSignal(bar, 1, callScore, putScore,
                    rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                    atrOk, adxOk, bbwOk, slopeOk, pivDist, "ReversalV15_CALL");
         return;
        }
     }

   // ── Verifica sinal PUT ─────────────────────────────────────────────
   if(putScore >= scoreMin && (putScore - callScore) >= InpScoreGapMin && regimeOk)
     {
      if(CheckStructuralFilter(bar, -1))  // -1 = PUT
        {
         double pivDist = FindPivotDist(bar, -1);

         EmitSignal(bar, -1, callScore, putScore,
                    rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                    atrOk, adxOk, bbwOk, slopeOk, pivDist, "ReversalV15_PUT");
         return;
        }
     }

   // ── Fallback — padrões clássicos (Harami, Engolfo, Pinça, Hammer) ──
   // Ativado quando V15 não atinge o mínimo, mas padrões gráficos estão presentes
   int bestScore = (callScore > putScore) ? callScore : putScore;

   // Para M15 o fallback exige score próximo do mínimo (evita sinais de baixa qualidade)
   bool fallbackM15Ok = (g_tf != 15) || (bestScore >= InpFallbackMinM15);

   if(fallbackM15Ok)
     {
      // Padrões baixistas (PUT)
      string patName = "";
      int    fallDir = 0;
      if(IsHaramiBearish(bar))         { patName = "HaramiBearish";  fallDir = -1; }
      else if(IsEngulfingBearish(bar)) { patName = "EngolfoBearish"; fallDir = -1; }
      else if(IsTweezerTop(bar))       { patName = "TweezerTop";     fallDir = -1; }
      // Padrões altistas (CALL)
      else if(IsHaramiBullish(bar))    { patName = "HaramiBullish";  fallDir =  1; }
      else if(IsEngulfingBullish(bar)) { patName = "EngolfoBullish"; fallDir =  1; }
      else if(IsTweezerBottom(bar))    { patName = "TweezerBottom";  fallDir =  1; }
      else if(IsHammer(bar))           { patName = "Hammer";         fallDir =  1; }

      if(fallDir != 0 && patName != "")
        {
         if(CheckStructuralFilter(bar, fallDir))
           {
            double pivDist = FindPivotDist(bar, fallDir);
            EmitSignal(bar, fallDir, callScore, putScore,
                       rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                       atrOk, adxOk, bbwOk, slopeOk, pivDist, patName);
           }
        }
     }
  }

// =======================================================================
// EmitSignal — Desenha seta e dispara alertas/CSV para um sinal
// dir: 1 = CALL, -1 = PUT
// =======================================================================
void EmitSignal(int bar, int dir,
                int callScore, int putScore,
                int rsiPts, int bbPts, int wickPts, int impPts, int kelPts, int engPts,
                bool atrOk, bool adxOk, bool bbwOk, bool slopeOk,
                double pivDist, string pattern)
  {
   // Desenha seta no buffer correspondente
   if(dir == 1)
     {
      BuyArrow[bar]  = Low[bar]  - iATR(NULL, 0, 14, bar) * 0.5;
      SellArrow[bar] = EMPTY_VALUE;
     }
   else
     {
      SellArrow[bar] = High[bar] + iATR(NULL, 0, 14, bar) * 0.5;
      BuyArrow[bar]  = EMPTY_VALUE;
     }

   // Alertas e CSV apenas para barra 1 (tempo real) dentro da janela de entrada
   if(bar == 1)
     {
      // Verifica confirmação (opcional)
      bool confirmed = true;
      if(InpConfirmEnable)
        {
         double pRef   = Close[1]; // fechamento da vela candidata
         double cPrice = Close[0]; // preço atual (vela em formação)
         if(g_tf == 15)
           {
            double priceBuffer = iATR(NULL, 0, InpATRPeriod, 1) * 0.1;
            if(dir ==  1) confirmed = (cPrice > pRef + priceBuffer);
            else          confirmed = (cPrice < pRef - priceBuffer);
           }
         else
           {
            if(dir ==  1) confirmed = (cPrice > pRef);
            else          confirmed = (cPrice < pRef);
           }
        }

      if(!confirmed)
         return;

      // Verifica janela de entrada (segundos após abertura da barra)
      int entryWin = (g_tf == 5) ? InpEntryWindowM5 : InpEntryWindowM15;
      datetime barOpen = Time[1];
      datetime now     = TimeCurrent();
      if((now - barOpen) > entryWin)
         return;

      // Evita duplicar alerta para a mesma barra
      if(barOpen == g_lastSigTime)
         return;

      // Armazena informações do sinal para o painel
      g_lastSigTime  = barOpen;
      g_lastSigDir   = (dir == 1) ? "CALL" : "PUT";
      g_lastSigScore = (dir == 1) ? callScore : putScore;
      g_lastCallScr  = callScore;
      g_lastPutScr   = putScore;
      g_lastSigPat   = pattern;
      g_lastRsiPts   = rsiPts;
      g_lastBbPts    = bbPts;
      g_lastWickPts  = wickPts;
      g_lastImpPts   = impPts;
      g_lastKelPts   = kelPts;
      g_lastEngPts   = engPts;
      g_lastAtrOk    = atrOk;
      g_lastAdxOk    = adxOk;
      g_lastBbwOk    = bbwOk;
      g_lastSlopeOk  = slopeOk;
      g_lastPivDist  = pivDist;

      // Dispara alertas
      string dirStr  = g_lastSigDir;
      string symbol  = Symbol();
      int    score   = g_lastSigScore;
      string tfStr   = IntegerToString(g_tf) + "m";
      string msgBody = StringFormat(
         "BOTDINVELAS V15 | %s | %s | %s | Score:%d | RSI:%d BB:%d Wick:%d Imp:%d Kel:%d Eng:%d",
         symbol, tfStr, dirStr, score,
         rsiPts, bbPts, wickPts, impPts, kelPts, engPts);

      if(InpAlertPopup)
         Alert(msgBody);
      if(InpAlertSound)
         PlaySound(InpSoundFile);
      if(InpPushNotif)
         SendNotification(msgBody);

      // Exporta para CSV
      if(InpExportCSV)
         ExportToCSV(barOpen, symbol, g_tf, dirStr, callScore, putScore, pattern,
                     rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                     atrOk, adxOk, bbwOk, slopeOk);
     }
  }

// =======================================================================
// FUNÇÕES DE SCORE — Tradução direta do Python V15
// =======================================================================

//--- RSI Score (0-25 pts)
// RSI ≤ oversold → 25 pts CALL | RSI ≤ oversold+10 → 12 pts CALL
// RSI ≥ overbought → 25 pts PUT | RSI ≥ overbought-10 → 12 pts PUT
void CalcRSIScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   double rsi = iRSI(NULL, 0, InpRSIPeriod, PRICE_CLOSE, bar);
   if(rsi <= InpRSIOversold)              { pts = 25; dir =  1; }
   else if(rsi <= InpRSIOversold + 10)   { pts = 12; dir =  1; }
   else if(rsi >= InpRSIOverbought)       { pts = 25; dir = -1; }
   else if(rsi >= InpRSIOverbought - 10) { pts = 12; dir = -1; }
  }

//--- BB Score (0-25 pts)
// Preço próximo/abaixo da banda inferior → CALL (proporcional à proximidade)
// Preço próximo/acima da banda superior → PUT
void CalcBBScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   double upper  = iBands(NULL, 0, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_UPPER, bar);
   double lower  = iBands(NULL, 0, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_LOWER, bar);
   double middle = iBands(NULL, 0, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_MAIN,  bar);
   if(upper == 0 && lower == 0) return;

   double price     = Close[bar];
   double bandWidth = MathMax(upper - lower, 1e-12);
   double proxThr   = bandWidth * InpBBProximity;
   double distLower = price - lower;
   double distUpper = upper - price;

   if(distLower < 0)                              { pts = 25; dir =  1; }  // abaixo da banda inferior
   else if(distLower >= 0 && distLower <= proxThr)
     {
      double frac = MathMax(0.0, 1.0 - distLower / MathMax(proxThr, 1e-12));
      pts = (int)(frac * 25); dir = 1;
     }
   else if(distUpper < 0)                         { pts = 25; dir = -1; }  // acima da banda superior
   else if(distUpper >= 0 && distUpper <= proxThr)
     {
      double frac = MathMax(0.0, 1.0 - distUpper / MathMax(proxThr, 1e-12));
      pts = (int)(frac * 25); dir = -1;
     }
  }

//--- Wick Score (0-25 pts)
// Sombra inferior dominante → CALL (suporte rejeitado)
// Sombra superior dominante → PUT (resistência rejeitada)
void CalcWickScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   double o = Open[bar],  c = Close[bar];
   double h = High[bar],  l = Low[bar];
   double rng        = MathMax(h - l, 1e-12);
   double lowerWick  = MathMin(o, c) - l;
   double upperWick  = h - MathMax(o, c);
   double lowerRatio = lowerWick / rng;
   double upperRatio = upperWick / rng;

   if(lowerRatio >= InpWickRatio && lowerRatio > upperRatio)
     {
      pts = (int)MathMin(25.0, lowerRatio * 35.0);
      dir =  1;  // CALL
     }
   else if(upperRatio >= InpWickRatio && upperRatio > lowerRatio)
     {
      pts = (int)MathMin(25.0, upperRatio * 35.0);
      dir = -1;  // PUT
     }
  }

//--- Impulso + Contexto Score (0-25 pts)
// Impulso = variação normalizada dos últimos ImpulseLookback fechamentos
// Contexto = comparação 1ª metade vs 2ª metade das últimas ContextLookback velas
// downtrend + impulso negativo → CALL (reversão)
// uptrend   + impulso positivo → PUT  (reversão)
void CalcImpulseScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   int totalBars = iBars(NULL, 0);
   if(bar + InpImpulseLookback + InpContextLookback + 5 >= totalBars)
      return;

   // Impulso: (Close[bar] - Close[bar+lookback]) / |Close[bar+lookback]|
   double cNow  = Close[bar];
   double cPast = Close[bar + InpImpulseLookback];
   if(MathAbs(cPast) < 1e-10) return;
   double impulse = (cNow - cPast) / MathAbs(cPast);

   // Contexto: comparação da 1ª metade (mais antiga) vs 2ª metade (mais recente)
   // das últimas ContextLookback velas ANTES da barra candidata (bar+1 .. bar+lookback+1)
   int    lb    = InpContextLookback;
   int    half  = lb / 2;
   double sumOld = 0.0, sumNew = 0.0;
   // Metade mais antiga: índices bar+half+1 .. bar+lb (mais distantes)
   for(int k = bar + half + 1; k <= bar + lb; k++)
      sumOld += Close[k];
   // Metade mais recente: índices bar+1 .. bar+half (mais próximas)
   for(int k = bar + 1; k <= bar + half; k++)
      sumNew += Close[k];

   if(half == 0 || lb - half == 0) return;
   double firstAvg  = sumOld / (lb - half);
   double secondAvg = sumNew / half;
   if(MathAbs(firstAvg) < 1e-10) return;
   double change = (secondAvg - firstAvg) / MathAbs(firstAvg);

   // Determina contexto
   string ctx = "sideways";
   if(change < -InpTrendThreshold) ctx = "downtrend";
   else if(change > InpTrendThreshold) ctx = "uptrend";

   // Pontua apenas quando contexto e impulso alinham (sinal de reversão)
   if(ctx == "downtrend" && impulse < -InpImpulseThreshold)
     {
      pts = (int)MathMin(25.0, MathAbs(impulse) * InpImpulseMultiplier);
      dir =  1;  // CALL
     }
   else if(ctx == "uptrend" && impulse > InpImpulseThreshold)
     {
      pts = (int)MathMin(25.0, MathAbs(impulse) * InpImpulseMultiplier);
      dir = -1;  // PUT
     }
  }

//--- Keltner Score (0-20 pts bônus)
// Middle = EMA(HLC3, period) | Offset = ATR(period) * shift [≈ RMA(TR)]
// Preço abaixo da banda inferior → CALL | acima da banda superior → PUT
void CalcKeltnerScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(!InpKeltnerEnable) return;

   // iMA com PRICE_TYPICAL = (H+L+C)/3 = HLC3 (correspondente ao Python)
   double keltMid    = iMA(NULL, 0, InpKeltnerPeriod, 0, MODE_EMA, PRICE_TYPICAL, bar);
   double keltOffset = iATR(NULL, 0, InpKeltnerPeriod, bar) * InpKeltnerShift;
   if(keltMid == 0 || keltOffset == 0) return;

   double keltUpper = keltMid + keltOffset;
   double keltLower = keltMid - keltOffset;
   double price     = Close[bar];
   double bandWidth = MathMax(keltUpper - keltLower, 1e-12);
   double prox      = bandWidth * 0.25;  // mesmo critério do BB_PROXIMITY
   double distLower = price - keltLower;
   double distUpper = keltUpper - price;

   if(distLower < 0)               { pts = 20; dir =  1; }  // abaixo do canal → CALL
   else if(distLower <= prox)
     {
      double frac = MathMax(0.0, 1.0 - distLower / MathMax(prox, 1e-12));
      pts = (int)(frac * 20); dir = 1;
     }
   else if(distUpper < 0)          { pts = 20; dir = -1; }  // acima do canal → PUT
   else if(distUpper <= prox)
     {
      double frac = MathMax(0.0, 1.0 - distUpper / MathMax(prox, 1e-12));
      pts = (int)(frac * 20); dir = -1;
     }
  }

//--- Engolfo / Pinça Score (0-20 pts bônus)
// Engolfo Bullish/Bearish: 20 pts | Tweezer Top/Bottom: 12 pts
void CalcEngulfScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(bar + 1 >= iBars(NULL, 0)) return;
   if(IsEngulfingBullish(bar))  { pts = 20; dir =  1; }
   else if(IsEngulfingBearish(bar)) { pts = 20; dir = -1; }
   else if(IsTweezerBottom(bar))    { pts = 12; dir =  1; }
   else if(IsTweezerTop(bar))       { pts = 12; dir = -1; }
  }

// =======================================================================
// FILTROS DE REGIME (regra 2-de-4)
// Permite até 2 filtros falhando; mais de 2 = sinal rejeitado
// =======================================================================
bool PassesRegimeFilters(int bar, bool &atrOk, bool &adxOk, bool &bbwOk, bool &slopeOk)
  {
   atrOk   = CheckATRFilter(bar);
   adxOk   = CheckADXFilter(bar);
   bbwOk   = CheckBBWidthFilter(bar);
   slopeOk = CheckSlopeFilter(bar);

   int failures = 0;
   if(!atrOk)   failures++;
   if(!adxOk)   failures++;
   if(!bbwOk)   failures++;
   if(!slopeOk) failures++;

   // Permite até 2 falhas (≥ 2 filtros devem passar)
   return(failures <= 2);
  }

//--- Filtro ATR: ATR/mean_close >= threshold adaptativo
bool CheckATRFilter(int bar)
  {
   if(!InpEnableATR) return(true);

   double atr = iATR(NULL, 0, InpATRPeriod, bar);
   if(atr <= 0) return(false);

   // Calcula média dos closes para normalização
   double sumClose = 0.0;
   for(int k = bar; k < bar + InpATRPeriod; k++)
      sumClose += Close[k];
   double meanClose = sumClose / InpATRPeriod;
   if(meanClose == 0) return(false);

   double ratio = atr / meanClose;

   // Atualiza fila adaptativa
   UpdateATRQueue(ratio);

   double thr = GetAdaptiveATRThreshold(ratio);
   return(ratio >= thr);
  }

//--- Atualiza a fila circular de ratios ATR para threshold adaptativo
void UpdateATRQueue(double ratio)
  {
   int qSize = MathMin(InpATRQueueSize, 30);
   if(g_tf == 5)
     {
      g_atrQueue5[g_atrQ5Idx] = ratio;
      g_atrQ5Idx = (g_atrQ5Idx + 1) % qSize;
      if(g_atrQ5Cnt < qSize) g_atrQ5Cnt++;
     }
   else
     {
      g_atrQueue15[g_atrQ15Idx] = ratio;
      g_atrQ15Idx = (g_atrQ15Idx + 1) % qSize;
      if(g_atrQ15Cnt < qSize) g_atrQ15Cnt++;
     }
  }

//--- Retorna threshold adaptativo ATR (mediana das últimas N leituras × fator)
double GetAdaptiveATRThreshold(double lastRatio)
  {
   double base    = (g_tf == 5) ? InpATRMinM5 : InpATRMinM15;
   double maxThr  = (g_tf == 5) ? InpATRMaxThrM5 : InpATRMaxThrM15;
   int    cnt     = (g_tf == 5) ? g_atrQ5Cnt : g_atrQ15Cnt;

   if(cnt < 10) return(base);  // fila insuficiente, usa mínimo absoluto

   // Copia os elementos válidos da fila circular para ordenação.
   // Para mediana, a ordem de inserção não importa — ArraySort reordena por valor.
   // Em fila circular parcialmente preenchida (cnt < 30), os elementos estão em
   // indices [0..cnt-1]. Em fila cheia (cnt == qSize), todos os 30 slots são válidos,
   // independente de onde o ponteiro circular aponta. A mediana é invariante à ordem.
   double tmpArr[];
   ArrayResize(tmpArr, cnt);
   if(g_tf == 5)
      ArrayCopy(tmpArr, g_atrQueue5, 0, 0, cnt);
   else
      ArrayCopy(tmpArr, g_atrQueue15, 0, 0, cnt);

   ArraySort(tmpArr);
   double med;
   if(cnt % 2 == 0) med = (tmpArr[cnt/2 - 1] + tmpArr[cnt/2]) / 2.0;
   else             med = tmpArr[cnt/2];

   double dyn = MathMax(base, med * InpATRAdaptFactor);
   dyn = MathMin(dyn, maxThr);
   return(MathMax(base, dyn));
  }

//--- Filtro ADX: iADX >= mínimo por timeframe
bool CheckADXFilter(int bar)
  {
   if(!InpEnableADX) return(true);
   double adx    = iADX(NULL, 0, InpADXPeriod, PRICE_CLOSE, MODE_MAIN, bar);
   double adxMin = (g_tf == 5) ? InpADXMinM5 : InpADXMinM15;
   return(adx >= adxMin);
  }

//--- Filtro BB Width: (upper-lower)/middle >= mínimo por timeframe
bool CheckBBWidthFilter(int bar)
  {
   if(!InpEnableBBW) return(true);
   double upper  = iBands(NULL, 0, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_UPPER, bar);
   double lower  = iBands(NULL, 0, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_LOWER, bar);
   double middle = iBands(NULL, 0, InpBBPeriod, InpBBStd, 0, PRICE_CLOSE, MODE_MAIN,  bar);
   if(middle == 0) return(false);
   double bbwMin = (g_tf == 5) ? InpBBWidthMinM5 : InpBBWidthMinM15;
   return((upper - lower) / middle >= bbwMin);
  }

//--- Filtro Slope EMA: |EMA[now]-EMA[now-lookback]|/close >= mínimo
bool CheckSlopeFilter(int bar)
  {
   if(!InpEnableSlope) return(true);
   double ema1 = iMA(NULL, 0, InpSlopeEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, bar);
   double ema2 = iMA(NULL, 0, InpSlopeEMAPeriod, 0, MODE_EMA, PRICE_CLOSE, bar + InpSlopeLookback);
   if(ema1 == 0 || ema2 == 0) return(false);
   double slope    = MathAbs(ema1 - ema2) / MathMax(Close[bar], 1e-10);
   double slopeMin = (g_tf == 5) ? InpSlopeMinM5 : InpSlopeMinM15;
   return(slope >= slopeMin);
  }

// =======================================================================
// FILTROS ESTRUTURAIS
// =======================================================================

//--- Filtro estrutural unificado: delega para M5 ou M15 dependendo do TF
bool CheckStructuralFilter(int bar, int dir)
  {
   if(g_tf == 5)  return(CheckM5ExtremeFilter(bar, dir));
   if(g_tf == 15) return(CheckM15StructuralFilter(bar, dir));
   return(true);
  }

//--- Filtro M5 Extreme: fechamento nos 20% extremos do range das últimas N velas
// CALL: close nos 20% mais baixos | PUT: close nos 20% mais altos
bool CheckM5ExtremeFilter(int bar, int dir)
  {
   if(!InpEnableM5Extreme) return(true);
   int totalBars = iBars(NULL, 0);
   int winEnd    = bar + InpM5ExtremeCandles + 1;
   if(winEnd >= totalBars) return(true);

   double rangeHigh = -DBL_MAX, rangeLow = DBL_MAX;
   for(int k = bar; k <= bar + InpM5ExtremeCandles; k++)
     {
      if(High[k] > rangeHigh) rangeHigh = High[k];
      if(Low[k]  < rangeLow)  rangeLow  = Low[k];
     }

   double rangeSize = rangeHigh - rangeLow;
   if(rangeSize < 1e-10) return(true);

   double cand      = Close[bar];
   double threshold = rangeSize * InpM5ExtremeFrac;

   if(dir ==  1) return(cand <= rangeLow  + threshold);  // CALL: nos 20% mais baixos
   if(dir == -1) return(cand >= rangeHigh - threshold);  // PUT:  nos 20% mais altos
   return(true);
  }

//--- Filtro M15 Structural: fechamento no 1/3 extremo do micro-range (closes)
// CALL: close no 1/3 inferior | PUT: close no 1/3 superior
bool CheckM15StructuralFilter(int bar, int dir)
  {
   if(!InpEnableM15Struct) return(true);
   int totalBars = iBars(NULL, 0);
   if(bar + InpM15StructCandles >= totalBars) return(true);

   double hi = -DBL_MAX, lo = DBL_MAX;
   for(int k = bar; k <= bar + InpM15StructCandles - 1; k++)
     {
      if(Close[k] > hi) hi = Close[k];
      if(Close[k] < lo) lo = Close[k];
     }
   double rng = hi - lo;
   if(rng < 1e-10) return(true);

   double cand  = Close[bar];
   double third = rng / 3.0;

   if(dir ==  1) return(cand <= lo + third);       // CALL: 1/3 inferior
   if(dir == -1) return(cand >= hi - third);       // PUT:  1/3 superior
   return(true);
  }

// =======================================================================
// DETECÇÃO DE PADRÕES DE VELA
// bar = vela candidata (last closed), bar+1 = vela anterior
// =======================================================================

//--- Engolfo de Alta (Bullish Engulfing)
// Vela atual alta engolfa corpo da vela prévia baixa
bool IsEngulfingBullish(int bar)
  {
   if(bar + 1 >= iBars(NULL, 0)) return(false);
   double o0 = Open[bar+1], c0 = Close[bar+1];  // vela anterior (mais velha)
   double o1 = Open[bar],   c1 = Close[bar];     // vela atual
   if(!(c0 < o0)) return(false);  // anterior deve ser baixa (bearish)
   if(!(c1 > o1)) return(false);  // atual deve ser alta (bullish)
   if(!(o1 <= c0 && c1 >= o0)) return(false);  // atual engolfa anterior
   double body0 = MathAbs(c0 - o0);
   double body1 = MathAbs(c1 - o1);
   return(body1 > body0 * 0.9);
  }

//--- Engolfo de Baixa (Bearish Engulfing)
// Vela atual baixa engolfa corpo da vela prévia alta
bool IsEngulfingBearish(int bar)
  {
   if(bar + 1 >= iBars(NULL, 0)) return(false);
   double o0 = Open[bar+1], c0 = Close[bar+1];
   double o1 = Open[bar],   c1 = Close[bar];
   if(!(c0 > o0)) return(false);  // anterior deve ser alta
   if(!(c1 < o1)) return(false);  // atual deve ser baixa
   if(!(o1 >= c0 && c1 <= o0)) return(false);
   double body0 = MathAbs(c0 - o0);
   double body1 = MathAbs(c1 - o1);
   return(body1 > body0 * 0.9);
  }

//--- Pinça de Fundo (Tweezer Bottom)
// Duas mínimas próximas: anterior baixa + atual alta → suporte / reversão altista
bool IsTweezerBottom(int bar)
  {
   if(bar + 1 >= iBars(NULL, 0)) return(false);
   double l0    = Low[bar+1], l1 = Low[bar];
   double avgLow = (l0 + l1) / 2.0;
   if(avgLow == 0) return(false);
   if(MathAbs(l0 - l1) / avgLow > 0.001) return(false);  // mínimas dentro de 0.1%
   return(Close[bar+1] < Open[bar+1] && Close[bar] > Open[bar]);
  }

//--- Pinça de Topo (Tweezer Top)
// Dois máximos próximos: anterior alta + atual baixa → resistência / reversão baixista
bool IsTweezerTop(int bar)
  {
   if(bar + 1 >= iBars(NULL, 0)) return(false);
   double h0     = High[bar+1], h1 = High[bar];
   double avgHigh = (h0 + h1) / 2.0;
   if(avgHigh == 0) return(false);
   if(MathAbs(h0 - h1) / avgHigh > 0.001) return(false);
   return(Close[bar+1] > Open[bar+1] && Close[bar] < Open[bar]);
  }

//--- Harami de Baixa (Bearish Harami)
// Corpo atual (baixa) contido dentro do corpo anterior (alta), < 80% do corpo anterior
bool IsHaramiBearish(int bar)
  {
   if(bar + 1 >= iBars(NULL, 0)) return(false);
   double o0 = Open[bar+1], c0 = Close[bar+1];
   double o1 = Open[bar],   c1 = Close[bar];
   if(!(c0 > o0 && c1 < o1)) return(false);  // anterior alta, atual baixa
   double hi0 = MathMax(o0, c0), lo0 = MathMin(o0, c0);
   double hi1 = MathMax(o1, c1), lo1 = MathMin(o1, c1);
   if(!(hi1 <= hi0 && lo1 >= lo0)) return(false);  // corpo atual dentro do anterior
   return(MathAbs(c1 - o1) < 0.8 * MathAbs(c0 - o0));
  }

//--- Harami de Alta (Bullish Harami)
// Corpo atual (alta) contido dentro do corpo anterior (baixa)
bool IsHaramiBullish(int bar)
  {
   if(bar + 1 >= iBars(NULL, 0)) return(false);
   double o0 = Open[bar+1], c0 = Close[bar+1];
   double o1 = Open[bar],   c1 = Close[bar];
   if(!(c0 < o0 && c1 > o1)) return(false);  // anterior baixa, atual alta
   double hi0 = MathMax(o0, c0), lo0 = MathMin(o0, c0);
   double hi1 = MathMax(o1, c1), lo1 = MathMin(o1, c1);
   if(!(hi1 <= hi0 && lo1 >= lo0)) return(false);
   return(MathAbs(c1 - o1) < 0.8 * MathAbs(c0 - o0));
  }

//--- Hammer
// Corpo pequeno (< 35% do range), sombra inferior longa (≥ 2x corpo), sombra superior pequena
bool IsHammer(int bar)
  {
   double o = Open[bar], c = Close[bar], h = High[bar], l = Low[bar];
   double body  = MathAbs(c - o);
   double rng   = MathMax(h - l, 1e-12);
   double upper = h - MathMax(o, c);
   double lower = MathMin(o, c) - l;
   if(body / rng > 0.35) return(false);
   if(lower < 2.0 * MathMax(body, 1e-12)) return(false);
   if(upper > 0.8 * MathMax(body, 1e-12)) return(false);
   return(true);
  }

// =======================================================================
// PIVÔS / FRACTAIS (left=2, right=2)
// Retorna a distância percentual ao pivô mais próximo na direção do sinal
// =======================================================================
double FindPivotDist(int bar, int dir)
  {
   if(!InpEnablePivots) return(1.0);
   int totalBars = iBars(NULL, 0);
   int left  = InpPivotLeft;
   int right = InpPivotRight;
   double price = Close[bar];
   if(price == 0) return(1.0);

   double bestDist = 1.0;
   bool   found    = false;

   // Busca por pivôs nos últimos 60 barras
   int searchEnd = MathMin(bar + 60, totalBars - right - 1);

   if(dir == 1)  // CALL: procura pivot_low mais recente
     {
      for(int i = bar + right; i <= searchEnd; i++)
        {
         bool isPivLow = true;
         double l = Low[i];
         for(int j = i - right; j < i; j++)
            if(Low[j] < l) { isPivLow = false; break; }
         if(isPivLow)
            for(int j = i + 1; j <= i + left; j++)
               if(j < totalBars && Low[j] < l) { isPivLow = false; break; }
         if(isPivLow)
           {
            double dist = MathAbs(price - l) / MathMax(MathAbs(l), 1e-12);
            if(!found || dist < bestDist) { bestDist = dist; found = true; }
            break;  // pivô mais recente encontrado
           }
        }
     }
   else  // PUT: procura pivot_high mais recente
     {
      for(int i = bar + right; i <= searchEnd; i++)
        {
         bool isPivHigh = true;
         double h = High[i];
         for(int j = i - right; j < i; j++)
            if(High[j] > h) { isPivHigh = false; break; }
         if(isPivHigh)
            for(int j = i + 1; j <= i + left; j++)
               if(j < totalBars && High[j] > h) { isPivHigh = false; break; }
         if(isPivHigh)
           {
            double dist = MathAbs(price - h) / MathMax(MathAbs(h), 1e-12);
            if(!found || dist < bestDist) { bestDist = dist; found = true; }
            break;
           }
        }
     }

   return(bestDist);
  }

// =======================================================================
// PAINEL INFORMATIVO (Dashboard)
// Exibe score breakdown, filtros e último sinal no canto do gráfico
// =======================================================================

// Lista de IDs de objetos criados para o painel
#define PANEL_N          18  // número de linhas do painel
#define PANEL_LINE_HEIGHT 16 // altura de cada linha do painel em pixels

void CreatePanel()
  {
   // Cria o fundo do painel (retângulo opaco)
   string bgName = PANEL_PREFIX + "BG";
   if(ObjectFind(0, bgName) < 0)
     {
      ObjectCreate(0, bgName, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, bgName, OBJPROP_CORNER,     CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, bgName, OBJPROP_XDISTANCE,  5);
      ObjectSetInteger(0, bgName, OBJPROP_YDISTANCE,  5);
      ObjectSetInteger(0, bgName, OBJPROP_XSIZE,      260);
      ObjectSetInteger(0, bgName, OBJPROP_YSIZE,      PANEL_N * PANEL_LINE_HEIGHT + 10);
      ObjectSetInteger(0, bgName, OBJPROP_BGCOLOR,    C'20,20,40');
      ObjectSetInteger(0, bgName, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(0, bgName, OBJPROP_COLOR,      clrDimGray);
      ObjectSetInteger(0, bgName, OBJPROP_BACK,       false);
      ObjectSetInteger(0, bgName, OBJPROP_SELECTABLE, false);
     }

   // Cria as linhas de texto do painel
   for(int i = 0; i < PANEL_N; i++)
     {
      string lbl = PANEL_PREFIX + "L" + IntegerToString(i);
      if(ObjectFind(0, lbl) < 0)
        {
         ObjectCreate(0, lbl, OBJ_LABEL, 0, 0, 0);
         ObjectSetInteger(0, lbl, OBJPROP_CORNER,     CORNER_RIGHT_UPPER);
         ObjectSetInteger(0, lbl, OBJPROP_XDISTANCE,  14);
         ObjectSetInteger(0, lbl, OBJPROP_YDISTANCE,  12 + i * PANEL_LINE_HEIGHT);
         ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE,   8);
         ObjectSetString (0, lbl, OBJPROP_FONT,       "Courier New");
         ObjectSetInteger(0, lbl, OBJPROP_COLOR,      clrSilver);
         ObjectSetInteger(0, lbl, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, lbl, OBJPROP_BACK,       false);
        }
     }
  }

void SetPanelLine(int row, string text, color clr = clrSilver)
  {
   string lbl = PANEL_PREFIX + "L" + IntegerToString(row);
   ObjectSetString (0, lbl, OBJPROP_TEXT,  text);
   ObjectSetInteger(0, lbl, OBJPROP_COLOR, clr);
  }

void UpdatePanel()
  {
   string sym   = Symbol();
   string tfStr = IntegerToString(g_tf) + "m";
   color  titleClr = clrDodgerBlue;
   color  sigClr   = (g_lastSigDir == "CALL") ? clrLime : (g_lastSigDir == "PUT" ? clrRed : clrSilver);

   // Filtros atuais (barra 1)
   bool atrOk, adxOk, bbwOk, slopeOk;
   PassesRegimeFilters(1, atrOk, adxOk, bbwOk, slopeOk);
   int failures = (!atrOk ? 1 : 0) + (!adxOk ? 1 : 0) + (!bbwOk ? 1 : 0) + (!slopeOk ? 1 : 0);
   string regStr = (failures <= 2) ? "PASS" : "FAIL";
   color  regClr = (failures <= 2) ? clrLime : clrRed;

   // Score atual (barra 1)
   int cs = (int)CallScoreBuffer[1];
   int ps = (int)PutScoreBuffer[1];

   // Direção do sinal atual (se houver)
   string nowDir = "";
   int scoreMin = (g_tf == 5) ? InpScoreMinM5 : InpScoreMinM15;
   if(cs >= scoreMin && (cs - ps) >= InpScoreGapMin) nowDir = "CALL ↑";
   else if(ps >= scoreMin && (ps - cs) >= InpScoreGapMin) nowDir = "PUT  ↓";
   else nowDir = "aguardando";

   // Timestamp do último sinal
   string lastSigStr = (g_lastSigTime > 0) ?
      TimeToString(g_lastSigTime, TIME_DATE | TIME_MINUTES) : "---";
   string lastSigInfo = (g_lastSigDir != "") ?
      g_lastSigDir + " | " + IntegerToString(g_lastSigScore) + "pts" : "---";

   // Distância ao pivô
   string pivStr = (g_lastPivDist < 0.99) ?
      StringFormat("%.3f%%", g_lastPivDist * 100.0) : "---";

   // Monta o painel linha por linha
   int r = 0;
   SetPanelLine(r++, "== BOTDINVELAS V15 [" + sym + " " + tfStr + "] ==", titleClr);
   SetPanelLine(r++, StringFormat("Score Atual  CALL:%d  PUT:%d", cs, ps));
   SetPanelLine(r++, StringFormat("Direção:     %s", nowDir),
                (nowDir == "CALL ↑") ? clrLime : (nowDir == "PUT  ↓" ? clrRed : clrSilver));

   // Score breakdown (último sinal)
   SetPanelLine(r++, "─── Breakdown ultimo sinal ───", clrDimGray);
   SetPanelLine(r++, StringFormat("RSI:%2d  BB:%2d  Wick:%2d  Imp:%2d",
                g_lastRsiPts, g_lastBbPts, g_lastWickPts, g_lastImpPts));
   SetPanelLine(r++, StringFormat("Kel:%2d  Eng:%2d  Call:%d  Put:%d",
                g_lastKelPts, g_lastEngPts, g_lastCallScr, g_lastPutScr));

   // Filtros de regime (atuais)
   SetPanelLine(r++, "─── Filtros de Regime (2/4) ──", clrDimGray);
   SetPanelLine(r++, StringFormat("ATR:%s  ADX:%s  BBW:%s  Slope:%s",
                atrOk   ? "✔" : "✘",
                adxOk   ? "✔" : "✘",
                bbwOk   ? "✔" : "✘",
                slopeOk ? "✔" : "✘"));
   SetPanelLine(r++, StringFormat("Falhas: %d/4  Regime: %s", failures, regStr), regClr);

   // Último sinal
   SetPanelLine(r++, "─── Último Sinal ─────────────", clrDimGray);
   SetPanelLine(r++, StringFormat("Dir: %-6s | Score: %d", g_lastSigDir, g_lastSigScore), sigClr);
   SetPanelLine(r++, StringFormat("Pat: %s", g_lastSigPat));
   SetPanelLine(r++, StringFormat("Hora: %s", lastSigStr));

   // Pivô
   SetPanelLine(r++, "─── Pivô Próximo ─────────────", clrDimGray);
   SetPanelLine(r++, StringFormat("Dist: %s (prox<0.2%%: %s)",
                pivStr,
                (g_lastPivDist <= InpPivotProxPct) ? "SIM" : "não"));

   // Janela de entrada
   int entryWin = (g_tf == 5) ? InpEntryWindowM5 : InpEntryWindowM15;
   int elapsed  = (int)(TimeCurrent() - Time[1]);
   int remaining = entryWin - elapsed;
   color winClr = (remaining > 0) ? clrYellow : clrDimGray;
   SetPanelLine(r++, StringFormat("Janela: %ds restantes", (remaining > 0) ? remaining : 0), winClr);
   SetPanelLine(r++, StringFormat("Min Score: M5=%d M15=%d  Gap:%d",
                InpScoreMinM5, InpScoreMinM15, InpScoreGapMin), clrDimGray);

   ChartRedraw(0);
  }

// =======================================================================
// EXPORTAÇÃO CSV
// Grava linha no arquivo CSV com todas as métricas do sinal
// =======================================================================
void ExportToCSV(datetime sigTime, string sym, int tf, string dir,
                 int callScore, int putScore, string pattern,
                 int rsiPts, int bbPts, int wickPts, int impPts, int kelPts, int engPts,
                 bool atrOk, bool adxOk, bool bbwOk, bool slopeOk)
  {
   if(!InpExportCSV) return;

   // Usa FileIsExist() para distinguir "arquivo novo" de "erro de permissão"
   bool fileExists = FileIsExist(InpCSVPath, 0);
   int  h;

   if(fileExists)
     {
      // Arquivo existente: abre para leitura+escrita e vai para o final (append)
      h = FileOpen(InpCSVPath, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
        {
         Print("BOTDINVELAS V15: Erro ao abrir CSV para append: ", InpCSVPath);
         return;
        }
      FileSeek(h, 0, SEEK_END);
     }
   else
     {
      // Arquivo inexistente: cria e escreve cabeçalho
      h = FileOpen(InpCSVPath, FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
        {
         Print("BOTDINVELAS V15: Erro ao criar CSV: ", InpCSVPath);
         return;
        }
      FileWriteString(h,
         "timestamp,symbol,timeframe,direction,call_score,put_score,"
         "pattern,rsi_pts,bb_pts,wick_pts,imp_pts,keltner_pts,engulf_pts,"
         "atr_ok,adx_ok,bbw_ok,slope_ok\n");
     }
   g_csvHdrWritten = true;

   // Linha de dados
   string line = StringFormat(
      "%s,%s,%dm,%s,%d,%d,%s,%d,%d,%d,%d,%d,%d,%s,%s,%s,%s\n",
      TimeToString(sigTime, TIME_DATE | TIME_SECONDS),
      sym, tf, dir,
      callScore, putScore, pattern,
      rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
      atrOk   ? "1" : "0",
      adxOk   ? "1" : "0",
      bbwOk   ? "1" : "0",
      slopeOk ? "1" : "0");

   FileWriteString(h, line);
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| Fim do indicador BOTDINVELAS_V15.mq4                             |
//+------------------------------------------------------------------+
