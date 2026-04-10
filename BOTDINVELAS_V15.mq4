//+------------------------------------------------------------------+
//|  BOTDINVELAS_V15.mq4                                             |
//|  Indicador de sinais para MetaTrader 4 - Motor V15 Definitivo    |
//|  Versao Qualidade Maxima: sistema dois estagios                  |
//|    Fase 1: Bolinha amarela (ARMADO) ao fechar vela               |
//|    Fase 2: Seta verde/vermelha (CONFIRMADO) ou Cruz (REJEITADO)  |
//|                                                                  |
//|  Traducao fiel do BOTDINVELAS M5/M15 v16 (Python -> MQL4)        |
//|  Timeframes: M5 e M15                                            |
//+------------------------------------------------------------------+
#property copyright   "BOTDINVELAS"
#property link        "https://github.com/edsmendanha/BOTDINVELASM1M5"
#property version     "15.4"
#property strict
#property description "Motor V15.4 Qualidade Maxima | Volume+Sessao+MTF+Divergencia+Log TXT | Dois estagios"

#property indicator_chart_window
#property indicator_buffers 14

// -- Cores dos buffers (indice 1-based para #property) ---------------
// Buffers 1-4: velas de alta (verde IQ Option)
#property indicator_color1  C'38,166,154'
#property indicator_color2  C'38,166,154'
#property indicator_color3  C'38,166,154'
#property indicator_color4  C'38,166,154'
// Buffers 5-8: velas de baixa (vermelho IQ Option)
#property indicator_color5  C'239,83,80'
#property indicator_color6  C'239,83,80'
#property indicator_color7  C'239,83,80'
#property indicator_color8  C'239,83,80'
// Buffer 9:  seta CALL confirmada (verde lima)
#property indicator_color9  clrLime
// Buffer 10: seta PUT confirmada (laranja-vermelho)
#property indicator_color10 clrOrangeRed
// Buffer 11: bolinha amarela - ARMADO (temporaria)
#property indicator_color11 clrGold
// Buffer 12: cruzinha cinza - REJEITADO (permanente)
#property indicator_color12 clrDarkGray

#property indicator_width9  3
#property indicator_width10 3
#property indicator_width11 2
#property indicator_width12 1

// =======================================================================
// INPUTS - Parametros configuraveis (todos com defaults de qualidade maxima)
// =======================================================================

//--- Score minimo V15
input int    V15_Score_Min_M5  = 68;   // Score minimo M5 (qualidade alta)
input int    V15_Score_Min_M15 = 65;   // Score minimo M15
input int    V15_Gap_Min       = 15;   // Diferenca minima call_score - put_score
input int    Min_Components    = 3;    // Minimo de componentes com score > 0

//--- RSI
input int    RSI_Period        = 14;   // Periodo RSI
input int    RSI_Oversold      = 30;   // RSI <= este = oversold -> 25pts CALL
input int    RSI_Overbought    = 70;   // RSI >= este = overbought -> 25pts PUT
input bool   RSI_Enable        = true; // Habilitar componente RSI

//--- Bollinger Bands
input int    BB_Period         = 20;   // Periodo Bollinger Bands
input double BB_StdDev         = 2.0;  // Multiplicador desvio padrao
input double BB_Proximity      = 0.25; // Fracao da largura considerada "proximo"
input bool   BB_Enable         = true; // Habilitar componente BB

//--- Wick (sombra)
input double Wick_Min_Ratio    = 0.45; // Razao minima sombra/range da vela
input int    Wick_Score_Max    = 25;   // Pontuacao maxima do wick
input int    Wick_Score_Factor = 35;   // Fator de conversao ratio -> pts
input bool   Wick_Enable       = true; // Habilitar componente Wick

//--- Impulso + Contexto
input int    Impulse_Lookback   = 5;      // Janela de impulso (velas)
input int    Context_Lookback   = 12;     // Janela de contexto (velas)
input double Trend_Threshold    = 0.0008; // Limiar para detectar tendencia
input double Impulse_Threshold  = 0.0006; // Limiar minimo do impulso
input int    Impulse_Multiplier = 8000;   // Fator impulso -> pontos
input bool   Impulse_Enable     = true;   // Habilitar componente Impulso

//--- Canal Keltner (bonus 0-20 pts)
input int    Keltner_Period     = 20;   // Periodo EMA/ATR Keltner
input double Keltner_Shift_Mult = 1.5;  // Multiplicador ATR Keltner
input bool   Keltner_Enable     = true; // Habilitar bonus Keltner

//--- Padroes de vela (bonus 0-20 pts)
input bool   Engulf_Enable      = true; // Habilitar bonus Engolfo/Pinca

//--- Filtros de regime (regra 3-de-4: maximo 1 falha)
input bool   Enable_Regime_Filter = true; // Habilitar filtros de regime
input int    Max_Regime_Failures  = 1;    // Maximo de filtros falhando (3-de-4)

input double ATR_Min_Ratio_M5  = 0.000020; // ATR/close minimo M5
input double ATR_Min_Ratio_M15 = 0.000060; // ATR/close minimo M15
input int    ATR_Period        = 14;        // Periodo ATR

input double ADX_Min_M5        = 9.0;  // ADX minimo M5
input double ADX_Min_M15       = 11.0; // ADX minimo M15
input int    ADX_Period        = 14;   // Periodo ADX

input double BBW_Min_M5        = 0.00050; // Largura BB minima M5
input double BBW_Min_M15       = 0.00110; // Largura BB minima M15

input double Slope_Min_M5      = 0.000050; // Slope EMA minimo M5
input double Slope_Min_M15     = 0.000120; // Slope EMA minimo M15
input int    Slope_EMA_Period  = 21;       // Periodo EMA slope
input int    Slope_Lookback    = 8;        // Janela de lookback slope

//--- Filtros estruturais
input bool   Enable_Structural_Filter = true; // Habilitar filtros estruturais
input int    M5_Extreme_Candles       = 20;   // Janela filtro extremo M5
input double M5_Extreme_Frac          = 0.20; // Fracao extremo M5 (20%)
input int    M15_Structural_Candles   = 5;    // Janela filtro estrutural M15

//--- Sistema de confirmacao (dois estagios)
input int    Confirm_Target_Seconds   = 20; // Janela de confirmacao (segundos)
input int    Confirm_Deadline_Seconds = 30; // Prazo maximo para confirmar

//--- Cooldown anti-cluster
input int    Cooldown_Bars_M5  = 6; // Barras de cooldown apos sinal confirmado M5
input int    Cooldown_Bars_M15 = 3; // Barras de cooldown apos sinal confirmado M15

//--- Fallback padroes classicos
input int    V15_Fallback_Near_Score = 38;   // Score minimo para fallback M15
input bool   Fallback_Enable         = true; // Habilitar fallback de padroes

//--- Volume Tick Filter
input bool   Enable_Volume_Filter = true;   // Habilitar filtro de volume tick
input int    Volume_Lookback      = 20;     // Janela para calcular media de volume
input double Volume_Min_Ratio     = 0.60;   // Volume minimo = 60% da media

//--- Filtro de Sessao (horario de mercado)
input bool   Enable_Session_Filter = true;  // Habilitar filtro de sessao de mercado
input int    Session_Score_Penalty = 10;    // Penalidade de score fora do horario prime
input int    Session_London_Start  = 8;     // Inicio sessao Londres (hora UTC)
input int    Session_London_End    = 12;    // Fim sessao Londres (hora UTC)
input int    Session_NY_Start      = 13;    // Inicio sessao NY (hora UTC)
input int    Session_NY_End        = 17;    // Fim sessao NY (hora UTC)
input int    Session_Asia_Start    = 0;     // Inicio sessao Asia (hora UTC)
input int    Session_Asia_End      = 3;     // Fim sessao Asia (hora UTC)

//--- Filtro Multi-Timeframe M15->M5 (so aplica no M5)
input bool   Enable_MTF_Filter    = true;    // Habilitar confirmacao multi-timeframe
input double MTF_RSI_Block_High   = 65.0;   // RSI M15 acima disto bloqueia CALL no M5
input double MTF_RSI_Block_Low    = 35.0;   // RSI M15 abaixo disto bloqueia PUT no M5
input double MTF_Slope_Threshold  = 0.0005; // Inclinacao minima da EMA M15 para bloquear

//--- Divergencia RSI (bonus de score)
input bool   Enable_RSI_Divergence   = true;  // Habilitar bonus por divergencia RSI
input int    Divergence_Bonus        = 15;    // Pontos bonus por divergencia confirmada
input int    Divergence_Lookback     = 10;    // Janela para buscar divergencia (velas)
input double Divergence_Bull_MaxRSI  = 50.0;  // RSI atual maximo para divergencia bullish
input double Divergence_Bull_PastRSI = 45.0;  // RSI passado maximo para divergencia bullish
input double Divergence_Bear_MinRSI  = 50.0;  // RSI atual minimo para divergencia bearish
input double Divergence_Bear_PastRSI = 55.0;  // RSI passado minimo para divergencia bearish

//--- Visual
input bool   Candle_Color_Enable = true;           // Colorir velas estilo IQ Option
input color  Candle_Bull_Color   = C'38,166,154';  // Verde IQ (#26A69A)
input color  Candle_Bear_Color   = C'239,83,80';   // Vermelho IQ (#EF5350)
input int    Arrow_Size          = 3; // Tamanho das setas confirmadas
input int    Dot_Size            = 2; // Tamanho da bolinha armada
input int    Cross_Size          = 1; // Tamanho da cruzinha rejeitada

//--- Dashboard
input bool   Dashboard_Enable   = true; // Exibir painel informativo
input int    Dashboard_FontSize = 9;    // Tamanho da fonte do painel

//--- CSV
input bool   Enable_CSV         = true;                      // Exportar sinais para CSV
input string CSV_Filename       = "signals_botdinvelas.csv"; // Nome do arquivo

//--- Log TXT organizado
input bool   Enable_TXT_Log    = true;                         // Habilitar log TXT organizado
input string TXT_Log_Filename  = "BOTDINVELAS_sinais.txt";     // Nome do arquivo TXT
input bool   TXT_Log_Breakdown = true;                         // Incluir breakdown dos componentes

//--- Alertas (apenas em CONFIRMADO)
input bool   Alert_Popup       = true;        // Popup ao confirmar sinal
input bool   Alert_Sound       = true;        // Som ao confirmar sinal
input string Alert_Sound_File  = "alert.wav"; // Arquivo de som
input bool   Alert_Push        = false;       // Push notification

// =======================================================================
// BUFFERS DE INDICADOR (14 no total)
// =======================================================================

// Velas de alta (buffers auxiliares, coloracao gerenciada pelo grafico)
double BullOpen[];   // buffer 0
double BullHigh[];   // buffer 1
double BullLow[];    // buffer 2
double BullClose[];  // buffer 3

// Velas de baixa (buffers auxiliares, coloracao gerenciada pelo grafico)
double BearOpen[];   // buffer 4
double BearHigh[];   // buffer 5
double BearLow[];    // buffer 6
double BearClose[];  // buffer 7

// Sinais
double BuyArrow[];   // buffer 8  - seta verde (CALL confirmado, permanente)
double SellArrow[];  // buffer 9  - seta vermelha (PUT confirmado, permanente)
double BulletBuf[];  // buffer 10 - bolinha ouro (ARMADO, temporaria)
double CrossBuf[];   // buffer 11 - cruzinha cinza (REJEITADO, permanente)

// Ocultos (data window)
double CallScoreBuf[]; // buffer 12 - score CALL da barra
double PutScoreBuf[];  // buffer 13 - score PUT da barra

// =======================================================================
// VARIAVEIS GLOBAIS DE ESTADO
// =======================================================================

// Timeframe detectado automaticamente
int g_tf = 0;

// Estado ARM: sinal detectado mas aguardando confirmacao
int      g_armedDir     = 0;   // 0=nenhum, 1=CALL, -1=PUT
datetime g_armedBarTime = 0;   // Time[1] quando armado (open-time da vela de sinal)
double   g_armedRef     = 0.0; // Close[1] no momento do armamento

// Detalhes do sinal armado (para CSV e dashboard)
int    g_armedCallScore  = 0;
int    g_armedPutScore   = 0;
int    g_armedRsiPts     = 0;
int    g_armedBbPts      = 0;
int    g_armedWickPts    = 0;
int    g_armedImpPts     = 0;
int    g_armedKelPts     = 0;
int    g_armedEngPts     = 0;
int    g_armedComponents = 0;
int    g_armedRegFails   = 0;
bool   g_armedStructOk   = false;
string g_armedPattern    = "";

// Cooldown: valor de Bars() no momento do ultimo confirme
int g_lastConfirmBars = -9999;

// Controle: evita reprocessar bar=1 no mesmo ciclo de nova barra
datetime g_lastProcessedBarTime = 0;

// Informacoes do ultimo sinal (para dashboard)
datetime g_lastSigTime   = 0;
string   g_lastSigDir    = "";
int      g_lastSigScore  = 0;
string   g_lastSigStatus = ""; // "CONFIRMADO" ou "REJEITADO"

// Estado dos novos filtros de qualidade (definido ao armar, usado no CSV e dashboard)
bool g_armedVolOk       = true;  // volume acima do minimo no momento do armamento
bool g_armedSessionPrime= true;  // estava em sessao prime ao armar
bool g_armedMtfOk       = true;  // MTF M15 nao contradizia a direcao ao armar
int  g_armedDivBonus    = 0;     // bonus de divergencia RSI aplicado ao score

// Constantes do painel
#define PANEL_PREFIX "BDV15_"
#define PANEL_LINES  16
#define LINE_H       15
#define MIN_BARS     60

// =======================================================================
// OnInit - Inicializacao dos buffers e painel
// =======================================================================
int OnInit()
  {
   g_tf = (int)Period();
   if(g_tf != 5 && g_tf != 15)
     {
      Alert("BOTDINVELAS V15: Indicador apenas para M5 e M15!");
      return(INIT_FAILED);
     }

   // -- Velas de alta (DRAW_NONE: buffers auxiliares, sem desenho proprio) ----
   SetIndexBuffer(0, BullOpen);
   SetIndexBuffer(1, BullHigh);
   SetIndexBuffer(2, BullLow);
   SetIndexBuffer(3, BullClose);
   SetIndexStyle(0, DRAW_NONE);
   SetIndexStyle(1, DRAW_NONE);
   SetIndexStyle(2, DRAW_NONE);
   SetIndexStyle(3, DRAW_NONE);
   SetIndexLabel(0, "Candle Alta");
   SetIndexEmptyValue(0, EMPTY_VALUE);
   SetIndexEmptyValue(1, EMPTY_VALUE);
   SetIndexEmptyValue(2, EMPTY_VALUE);
   SetIndexEmptyValue(3, EMPTY_VALUE);

   // -- Velas de baixa (DRAW_NONE: buffers auxiliares, sem desenho proprio) ---
   SetIndexBuffer(4, BearOpen);
   SetIndexBuffer(5, BearHigh);
   SetIndexBuffer(6, BearLow);
   SetIndexBuffer(7, BearClose);
   SetIndexStyle(4, DRAW_NONE);
   SetIndexStyle(5, DRAW_NONE);
   SetIndexStyle(6, DRAW_NONE);
   SetIndexStyle(7, DRAW_NONE);
   SetIndexLabel(4, "Candle Baixa");
   SetIndexEmptyValue(4, EMPTY_VALUE);
   SetIndexEmptyValue(5, EMPTY_VALUE);
   SetIndexEmptyValue(6, EMPTY_VALUE);
   SetIndexEmptyValue(7, EMPTY_VALUE);

   // -- Seta CALL confirmada (verde, Wingdings 233 = seta para cima) ---
   SetIndexBuffer(8, BuyArrow);
   SetIndexStyle(8, DRAW_ARROW, STYLE_SOLID, Arrow_Size, clrLime);
   SetIndexArrow(8, 233);
   SetIndexLabel(8, "CALL V15");
   SetIndexEmptyValue(8, EMPTY_VALUE);

   // -- Seta PUT confirmada (vermelho, Wingdings 234 = seta para baixo) -
   SetIndexBuffer(9, SellArrow);
   SetIndexStyle(9, DRAW_ARROW, STYLE_SOLID, Arrow_Size, clrOrangeRed);
   SetIndexArrow(9, 234);
   SetIndexLabel(9, "PUT V15");
   SetIndexEmptyValue(9, EMPTY_VALUE);

   // -- Bolinha ouro - ARMADO (Wingdings 108 = circulo preenchido) -----
   SetIndexBuffer(10, BulletBuf);
   SetIndexStyle(10, DRAW_ARROW, STYLE_SOLID, Dot_Size, clrGold);
   SetIndexArrow(10, 108);
   SetIndexLabel(10, "ARMADO");
   SetIndexEmptyValue(10, EMPTY_VALUE);

   // -- Cruzinha cinza - REJEITADO (Wingdings 251 = X) -----------------
   SetIndexBuffer(11, CrossBuf);
   SetIndexStyle(11, DRAW_ARROW, STYLE_SOLID, Cross_Size, clrDarkGray);
   SetIndexArrow(11, 251);
   SetIndexLabel(11, "REJEITADO");
   SetIndexEmptyValue(11, EMPTY_VALUE);

   // -- Buffers ocultos de score (data window) -------------------------
   SetIndexBuffer(12, CallScoreBuf);
   SetIndexStyle(12, DRAW_NONE);
   SetIndexLabel(12, "CallScore");
   SetIndexEmptyValue(12, 0.0);

   SetIndexBuffer(13, PutScoreBuf);
   SetIndexStyle(13, DRAW_NONE);
   SetIndexLabel(13, "PutScore");
   SetIndexEmptyValue(13, 0.0);

   // Reseta estado global
   g_armedDir             = 0;
   g_armedBarTime         = 0;
   g_lastProcessedBarTime = 0;
   g_lastConfirmBars      = -9999;
   g_lastSigTime          = 0;
   g_lastSigDir           = "";
   g_lastSigScore         = 0;
   g_lastSigStatus        = "";
   g_armedVolOk           = true;
   g_armedSessionPrime    = true;
   g_armedMtfOk           = true;
   g_armedDivBonus        = 0;

   // Cria painel informativo
   if(Dashboard_Enable) CreatePanel();

   IndicatorShortName("BOTDINVELAS V15.4 [" + IntegerToString(g_tf) + "m]");
   return(INIT_SUCCEEDED);
  }

// =======================================================================
// OnDeinit - Remove objetos do painel ao descarregar o indicador
// =======================================================================
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, PANEL_PREFIX);
  }

// =======================================================================
// OnCalculate - Loop principal (chamado a cada tick)
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
   if(rates_total < MIN_BARS) return(0);

   // -- 7a. Loop historico: processa barras fechadas (bar >= 2) ---------
   // Calcula ponto de inicio para processar apenas barras novas
   int startBar;
   if(prev_calculated <= 0)
      startBar = rates_total - MIN_BARS;
   else
      startBar = rates_total - prev_calculated;
   if(startBar < 2) startBar = 2;

   int lastHistSignalBar = 99999; // controle de cooldown no historico
   for(int bar = startBar; bar >= 2; bar--)
     {
      // Preenche buffers de vela colorida (IQ Option style)
      if(Candle_Color_Enable) PaintCandle(bar);

      // Calcula score V15 para esta barra historica
      int callScore, putScore, callComp, putComp;
      int rsiPts, bbPts, wickPts, impPts, kelPts, engPts;
      int rsiDir, bbDir, wickDir, impDir, kelDir, engDir;

      CalcV15Score(bar,
                   callScore, putScore, callComp, putComp,
                   rsiPts, rsiDir, bbPts, bbDir,
                   wickPts, wickDir, impPts, impDir,
                   kelPts, kelDir, engPts, engDir);

      CallScoreBuf[bar] = callScore;
      PutScoreBuf[bar]  = putScore;

      // Filtros de regime (3-de-4: max 1 falha)
      bool atrOk, adxOk, bbwOk, slopeOk;
      int regFails = CalcRegimeFails(bar, atrOk, adxOk, bbwOk, slopeOk);
      bool regimeOk = !Enable_Regime_Filter || (regFails <= Max_Regime_Failures);

      // Cooldown historico: pula plotagem se muito proximo do ultimo sinal confirmado
      int cooldownBarsH = (g_tf == 5) ? Cooldown_Bars_M5 : Cooldown_Bars_M15;
      if((lastHistSignalBar - bar) < cooldownBarsH) continue;

      // Filtro de volume: rejeita velas com volume abaixo da media
      if(!CheckVolumeFilter(bar)) continue;

      // Score minimo ajustado pela sessao de mercado
      int scoreMin = (g_tf == 5) ? V15_Score_Min_M5 : V15_Score_Min_M15;
      if(!IsInPrimeSession(bar)) scoreMin += Session_Score_Penalty;

      // Bonus de divergencia RSI
      int divBonusCallH = CalcDivergenceBonus(bar, 1);
      int divBonusPutH  = CalcDivergenceBonus(bar, -1);
      int adjCallScoreH = callScore + divBonusCallH;
      int adjPutScoreH  = putScore  + divBonusPutH;

      double atrVal = iATR(NULL, 0, ATR_Period, bar-1);

      // Determina direcao do sinal historico (se houver)
      int dir = 0;
      string histPattern = "";
      if(adjCallScoreH >= scoreMin &&
         (adjCallScoreH - adjPutScoreH) >= V15_Gap_Min &&
         callComp >= Min_Components && regimeOk &&
         CheckStructuralFilter(bar, 1) &&
         CheckMTFFilter(bar, 1))
        { dir = 1; histPattern = "ReversalV15_CALL"; }
      else if(adjPutScoreH >= scoreMin &&
              (adjPutScoreH - adjCallScoreH) >= V15_Gap_Min &&
              putComp >= Min_Components && regimeOk &&
              CheckStructuralFilter(bar, -1) &&
              CheckMTFFilter(bar, -1))
        { dir = -1; histPattern = "ReversalV15_PUT"; }
      // Fallback padroes classicos (score V15 nao atingiu o minimo)
      else if(Fallback_Enable && regimeOk)
        {
         int bestScore = (callScore > putScore) ? callScore : putScore;
         bool fbOk = (g_tf != 15) || (bestScore >= V15_Fallback_Near_Score);
         if(fbOk)
           {
            string patName = "";
            dir = CheckFallbackPatterns(bar, patName);
            if(dir != 0 &&
               (!CheckStructuralFilter(bar, dir) || !CheckMTFFilter(bar, dir)))
               dir = 0;
            if(dir != 0) histPattern = patName;
           }
        }

      // Simulacao historica de confirmacao na barra seguinte (bar-1)
      // "abriu na direcao" = Open da vela seguinte vs Close da vela de sinal
      if(dir != 0 && bar >= 2)
        {
         bool histConfirmed = (dir == 1) ? (Open[bar-1] > Close[bar])
                                         : (Open[bar-1] < Close[bar]);
         string histStatus = histConfirmed ? "CONFIRMED" : "REJECTED";
         int    histCall   = (dir == 1) ? adjCallScoreH : callScore;
         int    histPut    = (dir == -1) ? adjPutScoreH  : putScore;
         if(histConfirmed)
           {
            if(dir == 1) BuyArrow[bar-1]  = Low[bar-1]  - atrVal * 0.5;
            else         SellArrow[bar-1] = High[bar-1] + atrVal * 0.5;
            lastHistSignalBar = bar; // atualiza cooldown apos sinal confirmado
           }
         else
           {
            if(dir == 1) CrossBuf[bar-1]  = Low[bar-1]  - atrVal * 0.3;
            else         CrossBuf[bar-1]  = High[bar-1] + atrVal * 0.3;
           }
         // Grava sinal historico no log TXT (apenas na primeira passagem completa)
         if(prev_calculated <= 0)
            ExportTXT(Time[bar], histStatus, (dir==1)?"CALL":"PUT",
                      histCall, histPut, histPattern,
                      rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                      regFails, true);
        }
     }

   // -- 7b. Barra 1 (ultima fechada): verifica novo sinal para armar ---
   if(rates_total > 1)
     {
      if(Candle_Color_Enable) PaintCandle(1);
      ProcessBar1();
     }

   // -- Barra 0 (em formacao): gerencia confirmacao do sinal armado ----
   if(Candle_Color_Enable && rates_total > 0) PaintCandle(0);
   ProcessBar0();

   // Atualiza painel informativo
   if(Dashboard_Enable) UpdatePanel();

   return(rates_total);
  }

// =======================================================================
// PaintCandle - Preenche buffers de vela colorida para a barra indicada
// Bullish (close >= open): BullOpen/High/Low/Close
// Bearish (close < open):  BearOpen/High/Low/Close
// =======================================================================
void PaintCandle(int bar)
  {
   if(!Candle_Color_Enable) return;
   if(bar >= iBars(NULL, 0)) return;

   if(Close[bar] >= Open[bar])
     {
      BullOpen[bar]  = Open[bar];  BullHigh[bar]  = High[bar];
      BullLow[bar]   = Low[bar];   BullClose[bar] = Close[bar];
      BearOpen[bar]  = EMPTY_VALUE; BearHigh[bar]  = EMPTY_VALUE;
      BearLow[bar]   = EMPTY_VALUE; BearClose[bar] = EMPTY_VALUE;
     }
   else
     {
      BearOpen[bar]  = Open[bar];  BearHigh[bar]  = High[bar];
      BearLow[bar]   = Low[bar];   BearClose[bar] = Close[bar];
      BullOpen[bar]  = EMPTY_VALUE; BullHigh[bar]  = EMPTY_VALUE;
      BullLow[bar]   = EMPTY_VALUE; BullClose[bar] = EMPTY_VALUE;
     }
  }

// =======================================================================
// ProcessBar1 - Analisa a ultima barra fechada (bar=1) para armar sinal
// Executado UMA vez por nova barra (controlado por g_lastProcessedBarTime)
// =======================================================================
void ProcessBar1()
  {
   // Evita reprocessar a mesma barra em ticks consecutivos
   if(Time[1] == g_lastProcessedBarTime) return;
   g_lastProcessedBarTime = Time[1];

   // Verifica cooldown: quantas barras desde o ultimo confirme?
   int cooldown = (g_tf == 5) ? Cooldown_Bars_M5 : Cooldown_Bars_M15;
   if(g_lastConfirmBars > 0 && (Bars - g_lastConfirmBars) < cooldown)
      return; // ainda em cooldown, nao armar

   // Limpa estado de armamento anterior se houver (situacao excepcional)
   if(g_armedDir != 0) g_armedDir = 0;

   // Filtro de volume: rejeita se vela candidata tem volume abaixo da media
   if(!CheckVolumeFilter(1)) return;

   // Calcula todos os componentes do score V15 para bar=1
   int rsiPts=0,rsiDir=0, bbPts=0,bbDir=0, wickPts=0,wickDir=0;
   int impPts=0,impDir=0, kelPts=0,kelDir=0, engPts=0,engDir=0;

   CalcRSIScore(1,    rsiPts,  rsiDir);
   CalcBBScore(1,     bbPts,   bbDir);
   CalcWickScore(1,   wickPts, wickDir);
   CalcImpulseScore(1,impPts,  impDir);
   CalcKeltnerScore(1,kelPts,  kelDir);
   CalcEngulfScore(1, engPts,  engDir);

   // Acumula scores e conta componentes com pontuacao > 0 para cada direcao
   int callScore=0, putScore=0, callComp=0, putComp=0;
   if(rsiDir ==  1) { callScore += rsiPts;  if(rsiPts  > 0) callComp++; }
   if(rsiDir == -1) { putScore  += rsiPts;  if(rsiPts  > 0) putComp++;  }
   if(bbDir  ==  1) { callScore += bbPts;   if(bbPts   > 0) callComp++; }
   if(bbDir  == -1) { putScore  += bbPts;   if(bbPts   > 0) putComp++;  }
   if(wickDir== 1)  { callScore += wickPts; if(wickPts > 0) callComp++; }
   if(wickDir==-1)  { putScore  += wickPts; if(wickPts > 0) putComp++;  }
   if(impDir == 1)  { callScore += impPts;  if(impPts  > 0) callComp++; }
   if(impDir ==-1)  { putScore  += impPts;  if(impPts  > 0) putComp++;  }
   if(kelDir == 1)  { callScore += kelPts;  if(kelPts  > 0) callComp++; }
   if(kelDir ==-1)  { putScore  += kelPts;  if(kelPts  > 0) putComp++;  }
   if(engDir == 1)  { callScore += engPts;  if(engPts  > 0) callComp++; }
   if(engDir ==-1)  { putScore  += engPts;  if(engPts  > 0) putComp++;  }

   // Armazena nos buffers ocultos (data window)
   CallScoreBuf[1] = callScore;
   PutScoreBuf[1]  = putScore;

   // Filtros de regime (3-de-4: max 1 falha)
   bool atrOk, adxOk, bbwOk, slopeOk;
   int regFails = CalcRegimeFails(1, atrOk, adxOk, bbwOk, slopeOk);
   if(Enable_Regime_Filter && regFails > Max_Regime_Failures) return;

   // Score minimo ajustado pela sessao de mercado
   bool sessionPrime = IsInPrimeSession(1);
   int scoreMin = (g_tf == 5) ? V15_Score_Min_M5 : V15_Score_Min_M15;
   if(!sessionPrime) scoreMin += Session_Score_Penalty;

   // Bonus de divergencia RSI (somar ao score relevante)
   int divBonusCall = CalcDivergenceBonus(1, 1);
   int divBonusPut  = CalcDivergenceBonus(1, -1);
   int adjCallScore = callScore + divBonusCall;
   int adjPutScore  = putScore  + divBonusPut;

   // -- Tenta armar CALL -----------------------------------------------
   if(adjCallScore >= scoreMin &&
      (adjCallScore - adjPutScore) >= V15_Gap_Min &&
      callComp >= Min_Components &&
      CheckStructuralFilter(1, 1) &&
      CheckMTFFilter(1, 1))
     {
      g_armedVolOk        = true;
      g_armedSessionPrime = sessionPrime;
      g_armedMtfOk        = true;
      g_armedDivBonus     = divBonusCall;
      ArmSignal(1, 1, adjCallScore, adjPutScore,
                rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                callComp, regFails, "ReversalV15_CALL");
      return;
     }

   // -- Tenta armar PUT ------------------------------------------------
   if(adjPutScore >= scoreMin &&
      (adjPutScore - adjCallScore) >= V15_Gap_Min &&
      putComp >= Min_Components &&
      CheckStructuralFilter(1, -1) &&
      CheckMTFFilter(1, -1))
     {
      g_armedVolOk        = true;
      g_armedSessionPrime = sessionPrime;
      g_armedMtfOk        = true;
      g_armedDivBonus     = divBonusPut;
      ArmSignal(1, -1, adjCallScore, adjPutScore,
                rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                putComp, regFails, "ReversalV15_PUT");
      return;
     }

   // -- Fallback padroes classicos (score V15 nao atingiu o minimo) ----
   if(Fallback_Enable)
     {
      int bestScore = (callScore > putScore) ? callScore : putScore;
      bool fbOk = (g_tf != 15) || (bestScore >= V15_Fallback_Near_Score);
      if(fbOk)
        {
         string fbPat = "";
         int fbDir = CheckFallbackPatterns(1, fbPat);
         if(fbDir != 0 && CheckStructuralFilter(1, fbDir) && CheckMTFFilter(1, fbDir))
           {
            g_armedVolOk        = true;
            g_armedSessionPrime = sessionPrime;
            g_armedMtfOk        = true;
            g_armedDivBonus     = 0;
            ArmSignal(1, fbDir, callScore, putScore,
                      rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
                      (fbDir==1) ? callComp : putComp, regFails, fbPat);
           }
        }
     }
  }

// =======================================================================
// ArmSignal - Registra estado de armamento e plota bolinha amarela
// dir: 1=CALL, -1=PUT
// =======================================================================
void ArmSignal(int bar, int dir, int callScore, int putScore,
               int rsiPts, int bbPts, int wickPts, int impPts, int kelPts, int engPts,
               int components, int regFails, string pattern)
  {
   g_armedDir       = dir;
   g_armedBarTime   = Time[bar];
   g_armedRef       = Close[bar];
   g_armedCallScore = callScore;  g_armedPutScore = putScore;
   g_armedRsiPts    = rsiPts;     g_armedBbPts    = bbPts;
   g_armedWickPts   = wickPts;    g_armedImpPts   = impPts;
   g_armedKelPts    = kelPts;     g_armedEngPts   = engPts;
   g_armedComponents = components;
   g_armedRegFails  = regFails;
   g_armedStructOk  = true;
   g_armedPattern   = pattern;

   // Plota bolinha amarela: abaixo do low (CALL) ou acima do high (PUT)
   double atrVal = iATR(NULL, 0, ATR_Period, bar);
   if(dir == 1)
      BulletBuf[bar] = Low[bar]  - atrVal * 0.4;
   else
      BulletBuf[bar] = High[bar] + atrVal * 0.4;

   // Exporta CSV com status ARMED
   ExportCSV(Time[bar], "ARMED", (dir==1) ? "CALL" : "PUT",
             callScore, putScore, pattern,
             rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
             regFails, true);
   // Exporta TXT legivel com status ARMED
   ExportTXT(Time[bar], "ARMED", (dir==1) ? "CALL" : "PUT",
             callScore, putScore, pattern,
             rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
             regFails, true);
  }

// =======================================================================
// ProcessBar0 - Gerencia confirmacao do sinal armado (barra 0, em formacao)
// Chamado a cada tick enquanto houver sinal armado
// =======================================================================
void ProcessBar0()
  {
   if(g_armedDir == 0) return; // nenhum sinal armado

   // Localiza o indice atual da barra de sinal pelo timestamp
   int sigBarIdx = iBarShift(NULL, 0, g_armedBarTime, false);
   if(sigBarIdx < 0) { g_armedDir = 0; return; } // barra nao encontrada

   double atrNow = iATR(NULL, 0, ATR_Period, 0);

   // Se a barra de sinal esta em posicao > 1 (nova barra ja abriu):
   // o prazo de confirmacao expirou - rejeitar automaticamente
   if(sigBarIdx > 1)
     {
      BulletBuf[sigBarIdx] = EMPTY_VALUE; // remove bolinha da vela de sinal

      // Plota cruzinha na barra que era bar=0 quando o sinal foi armado
      int confIdx  = sigBarIdx - 1;
      double atrConf = iATR(NULL, 0, ATR_Period, confIdx);
      if(g_armedDir == 1)
         CrossBuf[confIdx] = Low[confIdx]  - atrConf * 0.3;
      else
         CrossBuf[confIdx] = High[confIdx] + atrConf * 0.3;

      ExportCSV(g_armedBarTime, "REJECTED", (g_armedDir==1)?"CALL":"PUT",
                g_armedCallScore, g_armedPutScore, g_armedPattern,
                g_armedRsiPts, g_armedBbPts, g_armedWickPts,
                g_armedImpPts, g_armedKelPts, g_armedEngPts,
                g_armedRegFails, g_armedStructOk);
      ExportTXT(g_armedBarTime, "REJECTED", (g_armedDir==1)?"CALL":"PUT",
                g_armedCallScore, g_armedPutScore, g_armedPattern,
                g_armedRsiPts, g_armedBbPts, g_armedWickPts,
                g_armedImpPts, g_armedKelPts, g_armedEngPts,
                g_armedRegFails, g_armedStructOk);

      g_lastSigTime   = g_armedBarTime;
      g_lastSigDir    = (g_armedDir==1) ? "CALL" : "PUT";
      g_lastSigScore  = (g_armedDir==1) ? g_armedCallScore : g_armedPutScore;
      g_lastSigStatus = "REJEITADO";
      g_armedDir = 0;
      ChartRedraw(0);
      return;
     }

   // Ainda na janela de confirmacao (bar 0 e a primeira vela apos o sinal)
   int elapsed = (int)(TimeCurrent() - Time[0]);

   // Verifica confirmacao dentro da janela alvo (primeiros Confirm_Target_Seconds)
   bool confirmed = false;
   if(elapsed <= Confirm_Target_Seconds)
     {
      // Preco atual (bid) deve ter se movido na direcao do sinal
      double bid = Bid;
      if(g_armedDir == 1)  confirmed = (bid > g_armedRef);
      else                 confirmed = (bid < g_armedRef);
     }

   if(confirmed)
     {
      // -- CONFIRMADO: plota seta permanente na barra 0 ----------------
      BulletBuf[sigBarIdx] = EMPTY_VALUE; // remove bolinha da vela de sinal

      if(g_armedDir == 1)
         BuyArrow[0]  = Low[0]  - atrNow * 0.5;
      else
         SellArrow[0] = High[0] + atrNow * 0.5;

      // Atualiza cooldown (bloqueia novos sinais pelas proximas N barras)
      g_lastConfirmBars = Bars;

      // Exporta CSV e dispara alertas
      ExportCSV(g_armedBarTime, "CONFIRMED", (g_armedDir==1)?"CALL":"PUT",
                g_armedCallScore, g_armedPutScore, g_armedPattern,
                g_armedRsiPts, g_armedBbPts, g_armedWickPts,
                g_armedImpPts, g_armedKelPts, g_armedEngPts,
                g_armedRegFails, g_armedStructOk);
      ExportTXT(g_armedBarTime, "CONFIRMED", (g_armedDir==1)?"CALL":"PUT",
                g_armedCallScore, g_armedPutScore, g_armedPattern,
                g_armedRsiPts, g_armedBbPts, g_armedWickPts,
                g_armedImpPts, g_armedKelPts, g_armedEngPts,
                g_armedRegFails, g_armedStructOk);

      SendAlerts((g_armedDir==1)?"CALL":"PUT",
                 (g_armedDir==1)?g_armedCallScore:g_armedPutScore);

      g_lastSigTime   = g_armedBarTime;
      g_lastSigDir    = (g_armedDir==1) ? "CALL" : "PUT";
      g_lastSigScore  = (g_armedDir==1) ? g_armedCallScore : g_armedPutScore;
      g_lastSigStatus = "CONFIRMADO";
      g_armedDir = 0;
      ChartRedraw(0);
      return;
     }

   // Prazo esgotado (elapsed > Confirm_Deadline_Seconds) - REJEITADO
   if(elapsed > Confirm_Deadline_Seconds)
     {
      BulletBuf[sigBarIdx] = EMPTY_VALUE;

      if(g_armedDir == 1)
         CrossBuf[0] = Low[0]  - atrNow * 0.3;
      else
         CrossBuf[0] = High[0] + atrNow * 0.3;

      ExportCSV(g_armedBarTime, "REJECTED", (g_armedDir==1)?"CALL":"PUT",
                g_armedCallScore, g_armedPutScore, g_armedPattern,
                g_armedRsiPts, g_armedBbPts, g_armedWickPts,
                g_armedImpPts, g_armedKelPts, g_armedEngPts,
                g_armedRegFails, g_armedStructOk);
      ExportTXT(g_armedBarTime, "REJECTED", (g_armedDir==1)?"CALL":"PUT",
                g_armedCallScore, g_armedPutScore, g_armedPattern,
                g_armedRsiPts, g_armedBbPts, g_armedWickPts,
                g_armedImpPts, g_armedKelPts, g_armedEngPts,
                g_armedRegFails, g_armedStructOk);

      g_lastSigTime   = g_armedBarTime;
      g_lastSigDir    = (g_armedDir==1) ? "CALL" : "PUT";
      g_lastSigScore  = (g_armedDir==1) ? g_armedCallScore : g_armedPutScore;
      g_lastSigStatus = "REJEITADO";
      g_armedDir = 0;
      ChartRedraw(0);
     }
  }

// =======================================================================
// CalcV15Score - Calcula o score composto V15 para a barra indicada
// Preenche todos os componentes e totais por referencia
// =======================================================================
void CalcV15Score(int bar,
                  int &callScore, int &putScore,
                  int &callComp,  int &putComp,
                  int &rsiPts,  int &rsiDir,
                  int &bbPts,   int &bbDir,
                  int &wickPts, int &wickDir,
                  int &impPts,  int &impDir,
                  int &kelPts,  int &kelDir,
                  int &engPts,  int &engDir)
  {
   callScore = 0; putScore = 0; callComp = 0; putComp = 0;

   CalcRSIScore(bar,    rsiPts,  rsiDir);
   CalcBBScore(bar,     bbPts,   bbDir);
   CalcWickScore(bar,   wickPts, wickDir);
   CalcImpulseScore(bar,impPts,  impDir);
   CalcKeltnerScore(bar,kelPts,  kelDir);
   CalcEngulfScore(bar, engPts,  engDir);

   if(rsiDir ==  1) { callScore += rsiPts;  if(rsiPts  > 0) callComp++; }
   if(rsiDir == -1) { putScore  += rsiPts;  if(rsiPts  > 0) putComp++;  }
   if(bbDir  ==  1) { callScore += bbPts;   if(bbPts   > 0) callComp++; }
   if(bbDir  == -1) { putScore  += bbPts;   if(bbPts   > 0) putComp++;  }
   if(wickDir== 1)  { callScore += wickPts; if(wickPts > 0) callComp++; }
   if(wickDir==-1)  { putScore  += wickPts; if(wickPts > 0) putComp++;  }
   if(impDir == 1)  { callScore += impPts;  if(impPts  > 0) callComp++; }
   if(impDir ==-1)  { putScore  += impPts;  if(impPts  > 0) putComp++;  }
   if(kelDir == 1)  { callScore += kelPts;  if(kelPts  > 0) callComp++; }
   if(kelDir ==-1)  { putScore  += kelPts;  if(kelPts  > 0) putComp++;  }
   if(engDir == 1)  { callScore += engPts;  if(engPts  > 0) callComp++; }
   if(engDir ==-1)  { putScore  += engPts;  if(engPts  > 0) putComp++;  }
  }

// =======================================================================
// FUNCOES DE SCORE V15 - Traducao direta do Python
// =======================================================================

// Componente 1: RSI (0-25 pts)
// RSI <= oversold       -> 25 pts CALL | RSI <= oversold+10  -> 12 pts CALL
// RSI >= overbought     -> 25 pts PUT  | RSI >= overbought-10 -> 12 pts PUT
void CalcRSIScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(!RSI_Enable) return;
   double rsi = iRSI(NULL, 0, RSI_Period, PRICE_CLOSE, bar);
   if(rsi <= RSI_Oversold)              { pts=25; dir= 1; }
   else if(rsi <= RSI_Oversold + 10)   { pts=12; dir= 1; }
   else if(rsi >= RSI_Overbought)       { pts=25; dir=-1; }
   else if(rsi >= RSI_Overbought - 10) { pts=12; dir=-1; }
  }

// Componente 2: Bollinger Bands (0-25 pts)
// Preco proximo/abaixo banda inferior -> CALL (proporcional a proximidade)
// Preco proximo/acima banda superior  -> PUT
void CalcBBScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(!BB_Enable) return;
   double upper  = iBands(NULL,0,BB_Period,BB_StdDev,0,PRICE_CLOSE,MODE_UPPER,bar);
   double lower  = iBands(NULL,0,BB_Period,BB_StdDev,0,PRICE_CLOSE,MODE_LOWER,bar);
   if(upper==0 && lower==0) return;
   double price     = Close[bar];
   double bandWidth = MathMax(upper - lower, 1e-12);
   double proxThr   = bandWidth * BB_Proximity;
   double distLower = price - lower;
   double distUpper = upper - price;
   if(distLower < 0)
     { pts=25; dir=1; }
   else if(distLower <= proxThr)
     { double f=MathMax(0.0,1.0-distLower/MathMax(proxThr,1e-12)); pts=(int)(f*25); dir=1; }
   else if(distUpper < 0)
     { pts=25; dir=-1; }
   else if(distUpper <= proxThr)
     { double f=MathMax(0.0,1.0-distUpper/MathMax(proxThr,1e-12)); pts=(int)(f*25); dir=-1; }
  }

// Componente 3: Wick / Sombra (0-25 pts)
// Sombra inferior dominante -> CALL (suporte rejeitado)
// Sombra superior dominante -> PUT (resistencia rejeitada)
void CalcWickScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(!Wick_Enable) return;
   double o=Open[bar], c=Close[bar], h=High[bar], l=Low[bar];
   double rng        = MathMax(h-l, 1e-12);
   double lowerWick  = MathMin(o,c) - l;
   double upperWick  = h - MathMax(o,c);
   double lowerRatio = lowerWick / rng;
   double upperRatio = upperWick / rng;
   if(lowerRatio >= Wick_Min_Ratio && lowerRatio > upperRatio)
     { pts=(int)MathMin((double)Wick_Score_Max, lowerRatio*Wick_Score_Factor); dir=1;  }
   else if(upperRatio >= Wick_Min_Ratio && upperRatio > lowerRatio)
     { pts=(int)MathMin((double)Wick_Score_Max, upperRatio*Wick_Score_Factor); dir=-1; }
  }

// Componente 4: Impulso + Contexto (0-25 pts)
// Impulso = variacao normalizada dos ultimos Impulse_Lookback fechamentos
// Contexto = 1a metade vs 2a metade do Context_Lookback (velas anteriores a candidata)
// downtrend + impulso negativo -> CALL (reversao de alta)
// uptrend   + impulso positivo -> PUT  (reversao de baixa)
void CalcImpulseScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(!Impulse_Enable) return;
   int totalBars = iBars(NULL, 0);
   if(bar + Impulse_Lookback + Context_Lookback + 5 >= totalBars) return;

   // Impulso: (Close[bar] - Close[bar+lookback]) / |Close[bar+lookback]|
   double cNow  = Close[bar];
   double cPast = Close[bar + Impulse_Lookback];
   if(MathAbs(cPast) < 1e-10) return;
   double impulse = (cNow - cPast) / MathAbs(cPast);

   // Contexto: velas ANTERIORES a candidata (bar+1 a bar+Context_Lookback)
   int lb   = Context_Lookback;
   int half = lb / 2;
   if(half == 0) return;
   double sumOld=0.0, sumNew=0.0;
   for(int k=bar+half+1; k<=bar+lb    && k<totalBars; k++) sumOld += Close[k];
   for(int k=bar+1;      k<=bar+half  && k<totalBars; k++) sumNew += Close[k];
   double firstAvg  = sumOld / (lb - half);
   double secondAvg = sumNew / half;
   if(MathAbs(firstAvg) < 1e-10) return;
   double change = (secondAvg - firstAvg) / MathAbs(firstAvg);

   // Classifica o contexto de tendencia
   string ctx = "sideways";
   if(change < -Trend_Threshold)    ctx = "downtrend";
   else if(change > Trend_Threshold) ctx = "uptrend";

   // Pontua apenas quando contexto e impulso convergem para reversao
   if(ctx=="downtrend" && impulse < -Impulse_Threshold)
     { pts=(int)MathMin(25.0, MathAbs(impulse)*Impulse_Multiplier); dir=1;  }
   else if(ctx=="uptrend" && impulse > Impulse_Threshold)
     { pts=(int)MathMin(25.0, MathAbs(impulse)*Impulse_Multiplier); dir=-1; }
  }

// Componente 5: Canal Keltner - bonus (0-20 pts)
// Middle = EMA(HLC3, Keltner_Period) | Offset = ATR(period) * Keltner_Shift_Mult
// Preco abaixo canal -> CALL | acima -> PUT (proporcional a proximidade)
void CalcKeltnerScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(!Keltner_Enable) return;
   double kMid    = iMA(NULL, 0, Keltner_Period, 0, MODE_EMA, PRICE_TYPICAL, bar);
   double kOffset = iATR(NULL, 0, Keltner_Period, bar) * Keltner_Shift_Mult;
   if(kMid==0 || kOffset==0) return;
   double kUpper    = kMid + kOffset;
   double kLower    = kMid - kOffset;
   double price     = Close[bar];
   double bandWidth = MathMax(kUpper-kLower, 1e-12);
   double prox      = bandWidth * 0.25;
   double distLower = price - kLower;
   double distUpper = kUpper - price;
   if(distLower < 0)
     { pts=20; dir=1; }
   else if(distLower <= prox)
     { double f=MathMax(0.0,1.0-distLower/MathMax(prox,1e-12)); pts=(int)(f*20); dir=1; }
   else if(distUpper < 0)
     { pts=20; dir=-1; }
   else if(distUpper <= prox)
     { double f=MathMax(0.0,1.0-distUpper/MathMax(prox,1e-12)); pts=(int)(f*20); dir=-1; }
  }

// Componente 6: Engolfo e Pinca - bonus (0-20 pts)
// Engolfo Bullish/Bearish -> 20 pts | Tweezer Bottom/Top -> 12 pts
void CalcEngulfScore(int bar, int &pts, int &dir)
  {
   pts = 0; dir = 0;
   if(!Engulf_Enable) return;
   if(bar+1 >= iBars(NULL, 0)) return;
   if(IsEngulfingBullish(bar))      { pts=20; dir=1;  }
   else if(IsEngulfingBearish(bar)) { pts=20; dir=-1; }
   else if(IsTweezerBottom(bar))    { pts=12; dir=1;  }
   else if(IsTweezerTop(bar))       { pts=12; dir=-1; }
  }

// =======================================================================
// FILTROS DE REGIME - Regra 3-de-4 (max 1 falha para PASSAR)
// =======================================================================

// Retorna numero de filtros falhando (0-4)
// Aprovado se resultado <= Max_Regime_Failures (padrao=1 -> 3-de-4)
int CalcRegimeFails(int bar, bool &atrOk, bool &adxOk, bool &bbwOk, bool &slopeOk)
  {
   atrOk   = CheckATRFilter(bar);
   adxOk   = CheckADXFilter(bar);
   bbwOk   = CheckBBWidthFilter(bar);
   slopeOk = CheckSlopeFilter(bar);
   int f = 0;
   if(!atrOk)   f++;
   if(!adxOk)   f++;
   if(!bbwOk)   f++;
   if(!slopeOk) f++;
   return(f);
  }

// Filtro ATR: volatilidade minima (ATR/close_medio >= threshold por timeframe)
bool CheckATRFilter(int bar)
  {
   double atr = iATR(NULL, 0, ATR_Period, bar);
   if(atr <= 0) return(false);
   double sumC = 0.0;
   int total = iBars(NULL, 0);
   for(int k=bar; k<bar+ATR_Period && k<total; k++) sumC += Close[k];
   double meanClose = sumC / ATR_Period;
   if(meanClose < 1e-10) return(false);
   double atrMin = (g_tf==5) ? ATR_Min_Ratio_M5 : ATR_Min_Ratio_M15;
   return(atr / meanClose >= atrMin);
  }

// Filtro ADX: direcionalidade minima (iADX >= threshold por timeframe)
bool CheckADXFilter(int bar)
  {
   double adx    = iADX(NULL, 0, ADX_Period, PRICE_CLOSE, MODE_MAIN, bar);
   double adxMin = (g_tf==5) ? ADX_Min_M5 : ADX_Min_M15;
   return(adx >= adxMin);
  }

// Filtro BB Width: largura minima das Bandas de Bollinger
bool CheckBBWidthFilter(int bar)
  {
   double upper  = iBands(NULL,0,BB_Period,BB_StdDev,0,PRICE_CLOSE,MODE_UPPER,bar);
   double lower  = iBands(NULL,0,BB_Period,BB_StdDev,0,PRICE_CLOSE,MODE_LOWER,bar);
   double middle = iBands(NULL,0,BB_Period,BB_StdDev,0,PRICE_CLOSE,MODE_MAIN, bar);
   if(middle < 1e-10) return(false);
   double bbwMin = (g_tf==5) ? BBW_Min_M5 : BBW_Min_M15;
   return((upper-lower)/middle >= bbwMin);
  }

// Filtro Slope EMA: inclinacao minima da EMA de fechamento
bool CheckSlopeFilter(int bar)
  {
   double ema1 = iMA(NULL,0,Slope_EMA_Period,0,MODE_EMA,PRICE_CLOSE,bar);
   double ema2 = iMA(NULL,0,Slope_EMA_Period,0,MODE_EMA,PRICE_CLOSE,bar+Slope_Lookback);
   if(ema1==0 || ema2==0) return(false);
   double slope    = MathAbs(ema1-ema2) / MathMax(Close[bar], 1e-10);
   double slopeMin = (g_tf==5) ? Slope_Min_M5 : Slope_Min_M15;
   return(slope >= slopeMin);
  }

// =======================================================================
// FILTROS ESTRUTURAIS
// =======================================================================

// Delega para M5 ou M15 conforme timeframe corrente
bool CheckStructuralFilter(int bar, int dir)
  {
   if(!Enable_Structural_Filter) return(true);
   if(g_tf == 5)  return(CheckM5ExtremeFilter(bar, dir));
   if(g_tf == 15) return(CheckM15StructuralFilter(bar, dir));
   return(true);
  }

// M5 Extreme: close nos 20% extremos do range das ultimas N velas
// CALL: close nos 20% mais baixos (fundo) | PUT: close nos 20% mais altos (topo)
bool CheckM5ExtremeFilter(int bar, int dir)
  {
   int total = iBars(NULL, 0);
   if(bar + M5_Extreme_Candles + 1 >= total) return(true);
   double rHigh=-DBL_MAX, rLow=DBL_MAX;
   for(int k=bar; k<=bar+M5_Extreme_Candles; k++)
     {
      if(High[k] > rHigh) rHigh = High[k];
      if(Low[k]  < rLow)  rLow  = Low[k];
     }
   double rng = rHigh - rLow;
   if(rng < 1e-10) return(true);
   double thr = rng * M5_Extreme_Frac;
   double c   = Close[bar];
   if(dir ==  1) return(c <= rLow  + thr);
   if(dir == -1) return(c >= rHigh - thr);
   return(true);
  }

// M15 Structural: close no 1/3 extremo do micro-range (closes das ultimas N velas)
// CALL: 1/3 inferior | PUT: 1/3 superior
bool CheckM15StructuralFilter(int bar, int dir)
  {
   int total = iBars(NULL, 0);
   if(bar + M15_Structural_Candles >= total) return(true);
   double hi=-DBL_MAX, lo=DBL_MAX;
   for(int k=bar; k<=bar+M15_Structural_Candles-1; k++)
     {
      if(Close[k] > hi) hi = Close[k];
      if(Close[k] < lo) lo = Close[k];
     }
   double rng = hi - lo;
   if(rng < 1e-10) return(true);
   double third = rng / 3.0;
   double c     = Close[bar];
   if(dir ==  1) return(c <= lo + third);
   if(dir == -1) return(c >= hi - third);
   return(true);
  }

// =======================================================================
// DETECCAO DE PADROES DE VELA
// =======================================================================

// Engolfo de Alta: vela bullish atual engolfa corpo da bearish anterior
bool IsEngulfingBullish(int bar)
  {
   if(bar+1 >= iBars(NULL,0)) return(false);
   double o0=Open[bar+1], c0=Close[bar+1]; // vela anterior
   double o1=Open[bar],   c1=Close[bar];   // vela atual
   if(!(c0<o0)) return(false); // anterior deve ser bearish
   if(!(c1>o1)) return(false); // atual deve ser bullish
   if(!(o1<=c0 && c1>=o0)) return(false); // engolfa o corpo
   return(MathAbs(c1-o1) > MathAbs(c0-o0)*0.9);
  }

// Engolfo de Baixa: vela bearish atual engolfa corpo da bullish anterior
bool IsEngulfingBearish(int bar)
  {
   if(bar+1 >= iBars(NULL,0)) return(false);
   double o0=Open[bar+1], c0=Close[bar+1];
   double o1=Open[bar],   c1=Close[bar];
   if(!(c0>o0)) return(false);
   if(!(c1<o1)) return(false);
   if(!(o1>=c0 && c1<=o0)) return(false);
   return(MathAbs(c1-o1) > MathAbs(c0-o0)*0.9);
  }

// Pinca de Fundo: minimas proximas, anterior bearish, atual bullish
bool IsTweezerBottom(int bar)
  {
   if(bar+1 >= iBars(NULL,0)) return(false);
   double l0=Low[bar+1], l1=Low[bar];
   double avg=(l0+l1)/2.0;
   if(avg<1e-10) return(false);
   if(MathAbs(l0-l1)/avg > 0.001) return(false);
   return(Close[bar+1]<Open[bar+1] && Close[bar]>Open[bar]);
  }

// Pinca de Topo: maximos proximos, anterior bullish, atual bearish
bool IsTweezerTop(int bar)
  {
   if(bar+1 >= iBars(NULL,0)) return(false);
   double h0=High[bar+1], h1=High[bar];
   double avg=(h0+h1)/2.0;
   if(avg<1e-10) return(false);
   if(MathAbs(h0-h1)/avg > 0.001) return(false);
   return(Close[bar+1]>Open[bar+1] && Close[bar]<Open[bar]);
  }

// Harami Bearish: corpo atual (bearish) contido no corpo anterior (bullish)
bool IsHaramiBearish(int bar)
  {
   if(bar+1 >= iBars(NULL,0)) return(false);
   double o0=Open[bar+1],c0=Close[bar+1];
   double o1=Open[bar],  c1=Close[bar];
   if(!(c0>o0 && c1<o1)) return(false);
   double hi0=MathMax(o0,c0), lo0=MathMin(o0,c0);
   double hi1=MathMax(o1,c1), lo1=MathMin(o1,c1);
   if(!(hi1<=hi0 && lo1>=lo0)) return(false);
   return(MathAbs(c1-o1) < 0.8*MathAbs(c0-o0));
  }

// Harami Bullish: corpo atual (bullish) contido no corpo anterior (bearish)
bool IsHaramiBullish(int bar)
  {
   if(bar+1 >= iBars(NULL,0)) return(false);
   double o0=Open[bar+1],c0=Close[bar+1];
   double o1=Open[bar],  c1=Close[bar];
   if(!(c0<o0 && c1>o1)) return(false);
   double hi0=MathMax(o0,c0), lo0=MathMin(o0,c0);
   double hi1=MathMax(o1,c1), lo1=MathMin(o1,c1);
   if(!(hi1<=hi0 && lo1>=lo0)) return(false);
   return(MathAbs(c1-o1) < 0.8*MathAbs(c0-o0));
  }

// Martelo (Hammer): corpo pequeno no topo, sombra inferior longa
bool IsHammer(int bar)
  {
   double o=Open[bar],c=Close[bar],h=High[bar],l=Low[bar];
   double body  = MathAbs(c-o);
   double rng   = MathMax(h-l, 1e-12);
   double upper = h - MathMax(o,c);
   double lower = MathMin(o,c) - l;
   if(body/rng > 0.35)                   return(false);
   if(lower < 2.0*MathMax(body,1e-12))  return(false);
   if(upper > 0.8*MathMax(body,1e-12))  return(false);
   return(true);
  }

// Verifica fallback de padroes classicos - retorna: 1=CALL, -1=PUT, 0=nenhum
int CheckFallbackPatterns(int bar, string &patName)
  {
   patName = "";
   if(IsHaramiBearish(bar))    { patName="HaramiBearish";  return(-1); }
   if(IsEngulfingBearish(bar)) { patName="EngolfoBearish"; return(-1); }
   if(IsTweezerTop(bar))       { patName="TweezerTop";     return(-1); }
   if(IsHaramiBullish(bar))    { patName="HaramiBullish";  return( 1); }
   if(IsEngulfingBullish(bar)) { patName="EngolfoBullish"; return( 1); }
   if(IsTweezerBottom(bar))    { patName="TweezerBottom";  return( 1); }
   if(IsHammer(bar))           { patName="Hammer";         return( 1); }
   return(0);
  }

// =======================================================================
// FILTROS DE QUALIDADE — Volume, Sessao, MTF, Divergencia RSI
// =======================================================================

// Filtro de Volume Tick: rejeita sinais em velas com volume abaixo da media
// Reversao sem volume = fakeout provavel
bool CheckVolumeFilter(int bar)
  {
   if(!Enable_Volume_Filter) return(true);
   int total = iBars(NULL, 0);
   if(bar + Volume_Lookback >= total) return(true);

   long currentVol = iVolume(NULL, 0, bar);
   if(currentVol <= 0) return(false);

   double sumVol = 0.0;
   for(int k = bar + 1; k <= bar + Volume_Lookback && k < total; k++)
      sumVol += (double)iVolume(NULL, 0, k);
   double avgVol = sumVol / Volume_Lookback;
   if(avgVol <= 0) return(true);

   return((double)currentVol >= avgVol * Volume_Min_Ratio);
  }

// Retorna a razao volume_atual / volume_medio para a barra indicada (para o painel)
double GetVolumeRatio(int bar)
  {
   int total = iBars(NULL, 0);
   if(bar + Volume_Lookback >= total) return(1.0);
   long currentVol = iVolume(NULL, 0, bar);
   if(currentVol <= 0) return(0.0);
   double sumVol = 0.0;
   for(int k = bar + 1; k <= bar + Volume_Lookback && k < total; k++)
      sumVol += (double)iVolume(NULL, 0, k);
   double avgVol = sumVol / Volume_Lookback;
   if(avgVol <= 0) return(1.0);
   return((double)currentVol / avgVol);
  }

// Filtro de Sessao: verifica se estamos em horario prime de mercado (UTC)
// Fora do horario prime, o score minimo eh elevado por Session_Score_Penalty
bool IsInPrimeSession(int bar)
  {
   if(!Enable_Session_Filter) return(true);

   int hour = TimeHour(Time[bar]);

   // Overlap Londres + NY = sessao PREMIUM (13-16 UTC)
   if(hour >= 13 && hour < 16) return(true);

   // Sessao Londres (08-12 UTC)
   if(hour >= Session_London_Start && hour < Session_London_End) return(true);

   // Sessao NY (13-17 UTC)
   if(hour >= Session_NY_Start && hour < Session_NY_End) return(true);

   // Sessao Asia (00-03 UTC) — qualidade media, aceita sem penalidade
   if(hour >= Session_Asia_Start && hour < Session_Asia_End) return(true);

   return(false); // fora de sessao: aplica penalidade de score
  }

// Filtro Multi-Timeframe: verifica se o M15 nao contradiz a direcao do sinal M5
// Aplica apenas quando g_tf == 5; sempre retorna true para M15
bool CheckMTFFilter(int bar, int dir)
  {
   if(!Enable_MTF_Filter) return(true);
   if(g_tf != 5)          return(true); // so aplica no M5

   // Encontra a barra M15 correspondente ao time da barra M5
   int m15bar = (bar == 0) ? 0 : iBarShift(NULL, PERIOD_M15, Time[bar], false);
   if(m15bar < 0) m15bar = 0;

   // RSI do M15: bloqueia CALL se sobrecomprado, PUT se sobrevendido
   double rsiM15 = iRSI(NULL, PERIOD_M15, RSI_Period, PRICE_CLOSE, m15bar);
   if(dir ==  1 && rsiM15 > MTF_RSI_Block_High) return(false);
   if(dir == -1 && rsiM15 < MTF_RSI_Block_Low)  return(false);

   // Tendencia da EMA21 no M15: bloqueia contra-tendencia forte
   double emaM15_now  = iMA(NULL, PERIOD_M15, 21, 0, MODE_EMA, PRICE_CLOSE, m15bar);
   double emaM15_prev = iMA(NULL, PERIOD_M15, 21, 0, MODE_EMA, PRICE_CLOSE, m15bar + 3);
   if(emaM15_now > 0 && emaM15_prev > 0)
     {
      double slopeM15 = (emaM15_now - emaM15_prev) / emaM15_now;
      double slopeM15 = (emaM15_now - emaM15_prev) / emaM15_now;
      if(dir ==  1 && slopeM15 < -MTF_Slope_Threshold) return(false); // M15 caindo forte, CALL perigoso
      if(dir == -1 && slopeM15 >  MTF_Slope_Threshold) return(false); // M15 subindo forte, PUT perigoso
     }

   return(true);
  }

// Bonus de Divergencia RSI: detecta divergencia entre preco e RSI
// Divergencia bullish: preco fez novo fundo, RSI fez fundo mais alto -> bônus CALL
// Divergencia bearish: preco fez novo topo, RSI fez topo mais baixo -> bonus PUT
int CalcDivergenceBonus(int bar, int dir)
  {
   if(!Enable_RSI_Divergence) return(0);
   int total = iBars(NULL, 0);
   if(bar + Divergence_Lookback >= total) return(0);

   double rsiNow   = iRSI(NULL, 0, RSI_Period, PRICE_CLOSE, bar);
   double priceNow = Close[bar];

   for(int k = bar + 3; k <= bar + Divergence_Lookback && k < total; k++)
     {
      double rsiPast   = iRSI(NULL, 0, RSI_Period, PRICE_CLOSE, k);
      double pricePast = Close[k];

      // Divergencia Bullish (CALL): preco fez novo fundo, RSI fez fundo mais alto
      if(dir == 1)
        {
         if(priceNow < pricePast && rsiNow > rsiPast)
           {
            if(rsiNow < Divergence_Bull_MaxRSI && rsiPast < Divergence_Bull_PastRSI) // ambos em zona de sobrevenda
               return(Divergence_Bonus);
           }
        }

      // Divergencia Bearish (PUT): preco fez novo topo, RSI fez topo mais baixo
      if(dir == -1)
        {
         if(priceNow > pricePast && rsiNow < rsiPast)
           {
            if(rsiNow > Divergence_Bear_MinRSI && rsiPast > Divergence_Bear_PastRSI) // ambos em zona de sobrecompra
               return(Divergence_Bonus);
           }
        }
     }

   return(0);
  }

// =======================================================================
// DASHBOARD - Painel informativo no canto superior direito
// =======================================================================
#define PANEL_BG_NAME PANEL_PREFIX+"BG"

void CreatePanel()
  {
   // Fundo semi-transparente escuro
   if(ObjectFind(0, PANEL_BG_NAME) < 0)
     {
      ObjectCreate(0, PANEL_BG_NAME, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_CORNER,     CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_XDISTANCE,  5);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_YDISTANCE,  5);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_XSIZE,      280);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_YSIZE,      PANEL_LINES*LINE_H+12);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_BGCOLOR,    C'18,22,36');
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_BORDER_TYPE,BORDER_FLAT);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_COLOR,      clrDimGray);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_BACK,       false);
      ObjectSetInteger(0, PANEL_BG_NAME, OBJPROP_SELECTABLE, false);
     }

   // Cria linhas de texto do painel
   for(int i=0; i<PANEL_LINES; i++)
     {
      string lbl = PANEL_PREFIX+"L"+IntegerToString(i);
      if(ObjectFind(0, lbl) < 0)
        {
         ObjectCreate(0, lbl, OBJ_LABEL, 0, 0, 0);
         ObjectSetInteger(0, lbl, OBJPROP_CORNER,     CORNER_RIGHT_UPPER);
         ObjectSetInteger(0, lbl, OBJPROP_XDISTANCE,  14);
         ObjectSetInteger(0, lbl, OBJPROP_YDISTANCE,  10 + i*LINE_H);
         ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE,   Dashboard_FontSize);
         ObjectSetString (0, lbl, OBJPROP_FONT,       "Courier New");
         ObjectSetInteger(0, lbl, OBJPROP_COLOR,      clrSilver);
         ObjectSetInteger(0, lbl, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, lbl, OBJPROP_BACK,       false);
        }
     }
  }

// Atualiza o texto e cor de uma linha do painel
void SetLine(int row, string text, color clr = clrSilver)
  {
   string lbl = PANEL_PREFIX+"L"+IntegerToString(row);
   ObjectSetString (0, lbl, OBJPROP_TEXT,  text);
   ObjectSetInteger(0, lbl, OBJPROP_COLOR, clr);
  }

// Atualiza o painel com os dados mais recentes (chamado a cada tick)
void UpdatePanel()
  {
   if(!Dashboard_Enable) return;

   // Scores e filtros da ultima barra fechada (bar=1)
   int cs = (int)CallScoreBuf[1];
   int ps = (int)PutScoreBuf[1];
   bool atrOk, adxOk, bbwOk, slopeOk;
   int regFails = CalcRegimeFails(1, atrOk, adxOk, bbwOk, slopeOk);
   bool regimeOk = (regFails <= Max_Regime_Failures);

   // Scores individuais dos componentes (bar=1) para exibicao detalhada
   int rP,rD, bP,bD, wP,wD, iP,iD, kP,kD, eP,eD;
   CalcRSIScore(1,rP,rD); CalcBBScore(1,bP,bD); CalcWickScore(1,wP,wD);
   CalcImpulseScore(1,iP,iD); CalcKeltnerScore(1,kP,kD); CalcEngulfScore(1,eP,eD);

   // Status atual do sistema
   string status = "IDLE";
   color  sClr   = clrSilver;
   if(g_armedDir != 0)
     { status=(g_armedDir==1)?"ARMADO CALL":"ARMADO PUT"; sClr=clrGold; }
   else if(g_lastSigStatus=="CONFIRMADO")
     { status="CONFIRMADO "+g_lastSigDir; sClr=clrLime; }
   else if(g_lastSigStatus=="REJEITADO")
     { status="REJEITADO "+g_lastSigDir; sClr=clrOrangeRed; }

   // Cooldown: barras restantes ate poder armar novo sinal
   int cooldown = (g_tf==5) ? Cooldown_Bars_M5 : Cooldown_Bars_M15;
   int cdDone   = (g_lastConfirmBars > 0) ? (Bars - g_lastConfirmBars) : cooldown;
   int cdLeft   = MathMax(0, cooldown - cdDone);
   bool inCD    = (cdLeft > 0);

   // Filtro estrutural da direcao predominante
   int cDir      = (cs >= ps) ? 1 : -1;
   bool structOk = CheckStructuralFilter(1, cDir);

   int r = 0;
   // L0: Titulo com timeframe e simbolo
   SetLine(r++, "BOTDINVELAS V15.4 | "+IntegerToString(g_tf)+"m | "+Symbol(), clrDodgerBlue);
   // L1: Scores dos componentes RSI / BB / Wick
   SetLine(r++, StringFormat("RSI:%2d | BB:%2d | Wick:%2d", rP, bP, wP));
   // L2: Scores dos componentes Impulso / Keltner / Engolfo
   SetLine(r++, StringFormat("Imp:%2d | KC:%2d | Eng:%2d",  iP, kP, eP));
   // L3: Scores totais CALL/PUT e gap
   SetLine(r++, StringFormat("CALL:%3d | PUT:%3d | GAP:%+3d", cs, ps, cs-ps));
   // L4: Status dos 4 filtros de regime
   SetLine(r++, StringFormat("ATR:%s|ADX:%s|BBW:%s|Slope:%s",
      atrOk?"OK":"--", adxOk?"OK":"--", bbwOk?"OK":"--", slopeOk?"OK":"--"));
   // L5: Resultado do filtro de regime (3-de-4)
   int scoreMin = (g_tf==5) ? V15_Score_Min_M5 : V15_Score_Min_M15;
   SetLine(r++, StringFormat("Regime:%d/4 falhas -> %s",
      regFails, regimeOk?"PASSA":"FALHA"),
      regimeOk ? clrLime : clrOrangeRed);
   // L6: Filtro estrutural
   SetLine(r++, "Estrutural: "+(structOk?"PASSA":"FALHA"),
      structOk ? clrLime : clrOrangeRed);
   // L7: Status atual (IDLE / ARMADO / CONFIRMADO / REJEITADO)
   SetLine(r++, "Status: "+status, sClr);
   // L8: Ultimo sinal confirmado ou rejeitado
   string last = "---";
   if(g_lastSigTime > 0)
      last = StringFormat("%s %dpts %s [%s]",
         g_lastSigDir, g_lastSigScore,
         TimeToString(g_lastSigTime, TIME_MINUTES), g_lastSigStatus);
   SetLine(r++, "Ultimo: "+last,
      (g_lastSigStatus=="CONFIRMADO")?clrLime:
      (g_lastSigStatus=="REJEITADO") ?clrOrangeRed:clrSilver);
   // L9: Cooldown
   SetLine(r++, StringFormat("Cooldown:%d/%d barras %s",
      MathMin(cdDone,cooldown), cooldown, inCD?"(aguard)":"(livre)"),
      inCD ? clrOrangeRed : clrLime);
   // L10: Parametros de qualidade (score min, gap, componentes)
   SetLine(r++, StringFormat("Min:score=%d gap=%d comps=%d",
      scoreMin, V15_Gap_Min, Min_Components), clrDimGray);
   // L11: Configuracao do regime
   SetLine(r++, StringFormat("MaxFails:%d | Regime:%s",
      Max_Regime_Failures, Enable_Regime_Filter?"ON":"OFF"), clrDimGray);

   // -- Novos filtros de qualidade V15.4 ---------------------------------
   // L12: Volume Tick Filter
   bool volOk      = CheckVolumeFilter(1);
   double volRatio = GetVolumeRatio(1);
   bool sessOk     = IsInPrimeSession(1);
   int  sessAdj    = sessOk ? 0 : Session_Score_Penalty;
   SetLine(r++, StringFormat("Volume: %s (%.0f%%) | Sessao: %s",
      volOk ? "OK" : "--",
      volRatio * 100.0,
      sessOk ? "PRIME" : StringFormat("OFF(+%dpts)", Session_Score_Penalty)),
      (!volOk || !sessOk) ? clrOrangeRed : clrLime);
   // L13: MTF M15 Filter
   int  cDirD    = (cs >= ps) ? 1 : -1;
   bool mtfOkD   = CheckMTFFilter(1, cDirD);
   int  m15barD  = iBarShift(NULL, PERIOD_M15, Time[1], false);
   if(m15barD < 0) m15barD = 0;
   int  rsiM15D  = (int)iRSI(NULL, PERIOD_M15, RSI_Period, PRICE_CLOSE, m15barD);
   SetLine(r++, StringFormat("MTF M15: %s | RSI M15: %d",
      mtfOkD ? "OK" : "--", rsiM15D),
      mtfOkD ? clrLime : clrOrangeRed);
   // L14: Divergencia RSI
   int divBonusD = CalcDivergenceBonus(1, cDirD);
   SetLine(r++, StringFormat("Divergencia RSI: %s",
      divBonusD > 0 ? StringFormat("+%dpts (bonus ativo)", divBonusD) : "---"),
      divBonusD > 0 ? clrGold : clrSilver);
   // L15: Score minimo efetivo (ajustado por sessao)
   SetLine(r++, StringFormat("ScoreMin efet: %d | Adj sessao: %+d",
      scoreMin + sessAdj, -sessAdj), clrDimGray);

   ChartRedraw(0);
  }

// =======================================================================
// EXPORTACAO CSV
// Formato: timestamp,symbol,timeframe,status,direction,call_score,put_score,
//          pattern,rsi,bb,wick,impulse,keltner,engulf,regime_fails,structural,
//          volume_ok,session_prime,mtf_ok,divergence_bonus
// O bot executor Python le este arquivo para decidir entradas
// =======================================================================
void ExportCSV(datetime sigTime, string status, string dir,
               int callScore, int putScore, string pattern,
               int rsiPts, int bbPts, int wickPts, int impPts, int kelPts, int engPts,
               int regFails, bool structOk)
  {
   if(!Enable_CSV) return;

   bool fileExists = FileIsExist(CSV_Filename, 0);
   int  h;

   if(fileExists)
     {
      h = FileOpen(CSV_Filename, FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI);
      if(h == INVALID_HANDLE) { Print("V15 CSV: erro ao abrir arquivo."); return; }
      FileSeek(h, 0, SEEK_END);
     }
   else
     {
      h = FileOpen(CSV_Filename, FILE_WRITE|FILE_TXT|FILE_ANSI);
      if(h == INVALID_HANDLE) { Print("V15 CSV: erro ao criar arquivo."); return; }
      // Escreve cabecalho na primeira vez
      FileWriteString(h,
         "timestamp,symbol,timeframe,status,direction,call_score,put_score,"
         "pattern,rsi,bb,wick,impulse,keltner,engulf,regime_fails,structural,"
         "volume_ok,session_prime,mtf_ok,divergence_bonus\n");
     }

   // Escreve linha com todos os dados do sinal (incluindo novos filtros V15.4)
   string line = StringFormat(
      "%s,%s,%dm,%s,%s,%d,%d,%s,%d,%d,%d,%d,%d,%d,%d,%s,%s,%s,%s,%d\n",
      TimeToString(sigTime, TIME_DATE|TIME_SECONDS),
      Symbol(), g_tf, status, dir,
      callScore, putScore, pattern,
      rsiPts, bbPts, wickPts, impPts, kelPts, engPts,
      regFails, structOk?"1":"0",
      g_armedVolOk?"1":"0",
      g_armedSessionPrime?"1":"0",
      g_armedMtfOk?"1":"0",
      g_armedDivBonus);

   FileWriteString(h, line);
   FileClose(h);
  }

// =======================================================================
// EXPORTACAO TXT ORGANIZADO — Log legivel multi-ativo
// Todos os graficos com o indicador escrevem no mesmo arquivo (FILE_COMMON)
// Caminho: AppData\Roaming\MetaQuotes\Terminal\Common\Files\<TXT_Log_Filename>
// =======================================================================
void ExportTXT(datetime sigTime, string status, string direction,
               int callScore, int putScore, string pattern,
               int rsiPts, int bbPts, int wickPts, int impPts, int kelPts, int engPts,
               int regFails, bool structOk)
  {
   if(!Enable_TXT_Log) return;

   // Abre o arquivo em modo append usando FILE_COMMON (compartilhado entre graficos)
   int handle = FileOpen(TXT_Log_Filename, FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      Print("V15 TXT: erro ao abrir arquivo de log.");
      return;
     }

   // Posiciona no final do arquivo para append
   FileSeek(handle, 0, SEEK_END);

   // Escreve cabecalho apenas quando o arquivo estiver vazio
   if(FileTell(handle) == 0)
     {
      FileWriteString(handle, "============================================================\r\n");
      FileWriteString(handle, "  BOTDINVELAS V15.4 \x2014 Log de Sinais\r\n");
      FileWriteString(handle, "  Gerado automaticamente pelo indicador MT4\r\n");
      FileWriteString(handle, "============================================================\r\n\r\n");
     }

   // Formata timestamp: YYYY-MM-DD HH:MM:SS
   string ts = TimeToString(sigTime, TIME_DATE|TIME_SECONDS);

   // Timeframe como texto
   string tf = IntegerToString(Period()) + "m";

   // Seta visual de direcao
   string arrow = (direction == "CALL") ? "CALL \x2191" : "PUT  \x2193";

   // Score principal (da direcao do sinal)
   int mainScore = (direction == "CALL") ? callScore : putScore;

   // Linha principal: [timestamp] SIMBOLO | TF | DIRECAO | Score: N | STATUS
   string line = "[" + ts + "] " + Symbol() + " | " + tf + " | " + arrow
               + " | Score: " + IntegerToString(mainScore) + " | " + status;
   FileWriteString(handle, line + "\r\n");

   // Breakdown detalhado dos componentes (opcional, apenas em ARMED e CONFIRMED)
   if(TXT_Log_Breakdown && (status == "CONFIRMED" || status == "ARMED"))
     {
      string detail = "             RSI:" + IntegerToString(rsiPts)
                    + " | BB:"   + IntegerToString(bbPts)
                    + " | Wick:" + IntegerToString(wickPts)
                    + " | Imp:"  + IntegerToString(impPts)
                    + " | KC:"   + IntegerToString(kelPts)
                    + " | Eng:"  + IntegerToString(engPts)
                    + " | CALL:" + IntegerToString(callScore)
                    + " vs PUT:" + IntegerToString(putScore)
                    + " | Regime:" + IntegerToString(4 - regFails) + "/4"
                    + " | Struct:" + (structOk ? "OK" : "FAIL")
                    + " | Pattern:" + pattern;
      FileWriteString(handle, detail + "\r\n");
     }

   // Linha separadora apos sinal confirmado ou rejeitado
   if(status == "CONFIRMED" || status == "REJECTED")
      FileWriteString(handle, "------------------------------------------------------------\r\n");

   FileClose(handle);
  }

// =======================================================================
// ALERTAS - Disparados APENAS em sinal CONFIRMADO (nunca em ARMADO/REJEITADO)
// =======================================================================
void SendAlerts(string dir, int score)
  {
   string sym   = Symbol();
   string tfStr = IntegerToString(g_tf)+"m";
   string msg   = StringFormat(
      "BOTDINVELAS V15.4 | %s %s | %s | Score:%d | %s",
      sym, tfStr, dir, score,
      TimeToString(TimeCurrent(), TIME_SECONDS));

   if(Alert_Popup) Alert(msg);
   if(Alert_Sound) PlaySound(Alert_Sound_File);
   if(Alert_Push)  SendNotification(msg);
  }

//+------------------------------------------------------------------+
//| Fim do indicador BOTDINVELAS_V15.mq4 - Versao 15.4              |
//| V15.4: Volume Tick + Session + MTF M15 + Divergencia RSI        |
//|        + Log TXT organizado multi-ativo (FILE_COMMON)           |
//+------------------------------------------------------------------+
