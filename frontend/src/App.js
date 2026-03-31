import { useState, useEffect, useCallback } from "react";
import "@/App.css";
import axios from "axios";
import { Toaster, toast } from "sonner";
import { Activity, Zap, TrendingUp, TrendingDown, Clock, Settings, Send, RefreshCw, Play, Square, AlertCircle, CheckCircle2, XCircle } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Slider } from "@/components/ui/slider";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Stat Card Component
const StatCard = ({ title, value, icon: Icon, trend, color = "cyan" }) => (
  <Card className="dashboard-card" data-testid={`stat-${title.toLowerCase().replace(/\s/g, '-')}`}>
    <CardContent className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs tracking-[0.1em] uppercase text-[#71717A] mb-1">{title}</p>
          <p className="font-mono text-2xl font-semibold text-[#FAFAFA]">{value}</p>
          {trend && (
            <p className={`text-xs mt-1 ${trend > 0 ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
              {trend > 0 ? '+' : ''}{trend}%
            </p>
          )}
        </div>
        <div className={`p-3 rounded-md ${color === 'green' ? 'bg-[#10B981]/15' : color === 'red' ? 'bg-[#EF4444]/15' : 'bg-[#00E5FF]/15'}`}>
          <Icon className={`h-5 w-5 ${color === 'green' ? 'text-[#10B981]' : color === 'red' ? 'text-[#EF4444]' : 'text-[#00E5FF]'}`} />
        </div>
      </div>
    </CardContent>
  </Card>
);

// Bot Status Component
const BotStatus = ({ status, onToggle, loading }) => (
  <Card className="dashboard-card" data-testid="bot-status-card">
    <CardContent className="p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`status-dot ${status.running ? 'status-running' : 'status-stopped'}`} />
          <div>
            <p className="font-chivo font-semibold text-[#FAFAFA]">
              Bot Status
            </p>
            <p className="text-xs text-[#71717A]">
              {status.running ? 'Monitoring 35 pairs' : 'Stopped'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Switch
            data-testid="bot-toggle"
            checked={status.running}
            onCheckedChange={onToggle}
            disabled={loading}
          />
          {status.running ? (
            <Square className="h-4 w-4 text-[#EF4444] cursor-pointer" onClick={() => onToggle(false)} />
          ) : (
            <Play className="h-4 w-4 text-[#10B981] cursor-pointer" onClick={() => onToggle(true)} />
          )}
        </div>
      </div>
      {status.last_analysis && (
        <p className="text-xs text-[#71717A] mt-3 font-mono">
          Last analysis: {new Date(status.last_analysis).toLocaleTimeString()}
        </p>
      )}
    </CardContent>
  </Card>
);

// Signal Row Component
const SignalRow = ({ signal }) => {
  const directionColor = signal.direction === 'BUY' ? 'text-[#10B981]' : 'text-[#EF4444]';
  const directionBg = signal.direction === 'BUY' ? 'bg-[#10B981]/15' : 'bg-[#EF4444]/15';
  
  const getResultBadge = () => {
    if (!signal.result) {
      return <Badge className="bg-[#F59E0B]/20 text-[#F59E0B] border-none">Pending</Badge>;
    }
    if (signal.result === 'WIN') {
      return <Badge className="bg-[#10B981]/20 text-[#10B981] border-none">WIN {signal.martingale_level > 0 ? `✅${signal.martingale_level}` : '✅'}</Badge>;
    }
    return <Badge className="bg-[#EF4444]/20 text-[#EF4444] border-none">LOSS ❌</Badge>;
  };

  return (
    <TableRow className="striped-row border-b border-[#ffffff]/5" data-testid={`signal-row-${signal.id}`}>
      <TableCell className="font-mono text-sm text-[#FAFAFA]">
        {signal.pair.replace('/', '')}-OTC
      </TableCell>
      <TableCell>
        <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${directionBg} ${directionColor}`}>
          {signal.direction === 'BUY' ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
          {signal.direction}
        </span>
      </TableCell>
      <TableCell className="font-mono text-sm text-[#A1A1AA]">{signal.entry_time}</TableCell>
      <TableCell className="font-mono text-sm text-[#A1A1AA]">{signal.confidence}%</TableCell>
      <TableCell className="font-mono text-xs text-[#71717A]">
        RSI: {signal.rsi}
      </TableCell>
      <TableCell>{getResultBadge()}</TableCell>
    </TableRow>
  );
};

// Pair Chip Component
const PairChip = ({ pair, hasActiveSignal }) => (
  <div 
    className={`pair-chip ${hasActiveSignal ? 'active-signal' : ''}`}
    data-testid={`pair-${pair.replace('/', '-')}`}
  >
    {pair}
  </div>
);

// Telegram Message Component
const TelegramMessage = ({ message }) => (
  <div className="telegram-message" data-testid={`telegram-msg-${message.id}`}>
    <pre className="whitespace-pre-wrap font-mono text-xs text-[#A1A1AA]">
      {message.message}
    </pre>
    <p className="text-[10px] text-[#71717A] mt-2">
      {new Date(message.sent_at).toLocaleString()}
    </p>
  </div>
);

// Config Panel Component
const ConfigPanel = ({ config, onUpdate, loading }) => {
  const [localConfig, setLocalConfig] = useState(config);

  useEffect(() => {
    setLocalConfig(config);
  }, [config]);

  const handleSave = () => {
    onUpdate(localConfig);
  };

  return (
    <Card className="dashboard-card" data-testid="config-panel">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 font-chivo text-[#FAFAFA]">
          <Settings className="h-4 w-4 text-[#00E5FF]" />
          Bot Configuration
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label className="text-xs text-[#71717A]">RSI Oversold</Label>
            <div className="flex items-center gap-2 mt-1">
              <Slider
                value={[localConfig.rsi_oversold || 30]}
                onValueChange={([v]) => setLocalConfig({...localConfig, rsi_oversold: v})}
                max={50}
                min={10}
                step={1}
                className="flex-1"
              />
              <span className="font-mono text-sm text-[#FAFAFA] w-8">{localConfig.rsi_oversold}</span>
            </div>
          </div>
          <div>
            <Label className="text-xs text-[#71717A]">RSI Overbought</Label>
            <div className="flex items-center gap-2 mt-1">
              <Slider
                value={[localConfig.rsi_overbought || 70]}
                onValueChange={([v]) => setLocalConfig({...localConfig, rsi_overbought: v})}
                max={90}
                min={50}
                step={1}
                className="flex-1"
              />
              <span className="font-mono text-sm text-[#FAFAFA] w-8">{localConfig.rsi_overbought}</span>
            </div>
          </div>
          <div>
            <Label className="text-xs text-[#71717A]">Stochastic Oversold</Label>
            <div className="flex items-center gap-2 mt-1">
              <Slider
                value={[localConfig.stochastic_oversold || 20]}
                onValueChange={([v]) => setLocalConfig({...localConfig, stochastic_oversold: v})}
                max={40}
                min={5}
                step={1}
                className="flex-1"
              />
              <span className="font-mono text-sm text-[#FAFAFA] w-8">{localConfig.stochastic_oversold}</span>
            </div>
          </div>
          <div>
            <Label className="text-xs text-[#71717A]">Stochastic Overbought</Label>
            <div className="flex items-center gap-2 mt-1">
              <Slider
                value={[localConfig.stochastic_overbought || 80]}
                onValueChange={([v]) => setLocalConfig({...localConfig, stochastic_overbought: v})}
                max={95}
                min={60}
                step={1}
                className="flex-1"
              />
              <span className="font-mono text-sm text-[#FAFAFA] w-8">{localConfig.stochastic_overbought}</span>
            </div>
          </div>
        </div>
        <div>
          <Label className="text-xs text-[#71717A]">Min Confidence (%)</Label>
          <div className="flex items-center gap-2 mt-1">
            <Slider
              value={[localConfig.min_confidence || 65]}
              onValueChange={([v]) => setLocalConfig({...localConfig, min_confidence: v})}
              max={90}
              min={50}
              step={5}
              className="flex-1"
            />
            <span className="font-mono text-sm text-[#FAFAFA] w-8">{localConfig.min_confidence}%</span>
          </div>
        </div>
        <Button 
          onClick={handleSave} 
          disabled={loading}
          className="w-full bg-[#00E5FF] hover:bg-[#00E5FF]/80 text-[#09090B] font-medium"
          data-testid="save-config-btn"
        >
          Save Configuration
        </Button>
      </CardContent>
    </Card>
  );
};

// Main Dashboard Component
function App() {
  const [botStatus, setBotStatus] = useState({ running: false, signals_sent: 0, total_wins: 0, total_losses: 0, win_rate: 0, last_analysis: null, pairs_monitoring: 35 });
  const [signals, setSignals] = useState([]);
  const [telegramMessages, setTelegramMessages] = useState([]);
  const [config, setConfig] = useState({});
  const [pairs, setPairs] = useState([]);
  const [stats, setStats] = useState({ total_signals: 0, wins: 0, losses: 0, pending: 0, win_rate: 0 });
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("signals");

  // Fetch data
  const fetchData = useCallback(async () => {
    try {
      const [statusRes, signalsRes, configRes, pairsRes, statsRes, telegramRes] = await Promise.all([
        axios.get(`${API}/bot/status`),
        axios.get(`${API}/signals?limit=50`),
        axios.get(`${API}/bot/config`),
        axios.get(`${API}/pairs`),
        axios.get(`${API}/stats`),
        axios.get(`${API}/telegram-messages?limit=20`)
      ]);
      
      setBotStatus(statusRes.data);
      setSignals(signalsRes.data);
      setConfig(configRes.data);
      setPairs(pairsRes.data.pairs);
      setStats(statsRes.data);
      setTelegramMessages(telegramRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, [fetchData]);

  // Toggle bot
  const toggleBot = async (start) => {
    setLoading(true);
    try {
      const endpoint = start ? `${API}/bot/start` : `${API}/bot/stop`;
      const response = await axios.post(endpoint);
      setBotStatus(prev => ({ ...prev, running: response.data.running }));
      toast.success(start ? "Bot started successfully" : "Bot stopped");
      fetchData();
    } catch (error) {
      toast.error("Failed to toggle bot");
    }
    setLoading(false);
  };

  // Update config
  const updateConfig = async (newConfig) => {
    setLoading(true);
    try {
      await axios.put(`${API}/bot/config`, newConfig);
      setConfig(newConfig);
      toast.success("Configuration updated");
    } catch (error) {
      toast.error("Failed to update config");
    }
    setLoading(false);
  };

  // Test Telegram
  const testTelegram = async () => {
    setLoading(true);
    try {
      const response = await axios.post(`${API}/test-telegram`);
      if (response.data.success) {
        toast.success("Test message sent to Telegram");
      } else {
        toast.error("Failed to send test message");
      }
      fetchData();
    } catch (error) {
      toast.error("Failed to test Telegram");
    }
    setLoading(false);
  };

  // Trigger analysis
  const triggerAnalysis = async () => {
    if (!botStatus.running) {
      toast.error("Start the bot first");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API}/analyze-now`);
      toast.success("Analysis triggered");
      setTimeout(fetchData, 3000);
    } catch (error) {
      toast.error("Failed to trigger analysis");
    }
    setLoading(false);
  };

  // Get active signal pairs
  const activePairs = signals.filter(s => !s.result).map(s => s.pair);

  return (
    <div className="dashboard-container min-h-screen" data-testid="trading-dashboard">
      <Toaster position="top-right" theme="dark" />
      
      {/* Header */}
      <header className="dashboard-header px-4 md:px-6 py-4" data-testid="dashboard-header">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-[#00E5FF]/15 rounded-md">
              <Activity className="h-6 w-6 text-[#00E5FF]" />
            </div>
            <div>
              <h1 className="font-chivo text-xl font-bold text-[#FAFAFA]">Dfg_2k Analysis</h1>
              <p className="text-xs text-[#71717A]">Pocket Option Trading Bot</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={testTelegram}
              disabled={loading}
              className="border-[#ffffff]/10 bg-transparent hover:bg-[#ffffff]/5 text-[#A1A1AA]"
              data-testid="test-telegram-btn"
            >
              <Send className="h-4 w-4 mr-2" />
              Test Telegram
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchData}
              disabled={loading}
              className="border-[#ffffff]/10 bg-transparent hover:bg-[#ffffff]/5 text-[#A1A1AA]"
              data-testid="refresh-btn"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="px-4 md:px-6 py-6">
        <div className="max-w-[1600px] mx-auto space-y-6">
          
          {/* Stats Row */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
            <BotStatus status={botStatus} onToggle={toggleBot} loading={loading} />
            <StatCard title="Win Rate" value={`${stats.win_rate}%`} icon={TrendingUp} color="green" />
            <StatCard title="Total Wins" value={stats.wins} icon={CheckCircle2} color="green" />
            <StatCard title="Total Losses" value={stats.losses} icon={XCircle} color="red" />
            <StatCard title="Pending" value={stats.pending} icon={Clock} color="cyan" />
          </div>

          {/* Main Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            
            {/* Left Column - Signals & Pairs */}
            <div className="lg:col-span-3 space-y-6">
              
              {/* Tabs */}
              <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
                <TabsList className="bg-[#121214] border border-[#ffffff]/10">
                  <TabsTrigger value="signals" className="data-[state=active]:bg-[#00E5FF]/15 data-[state=active]:text-[#00E5FF]">
                    Signals
                  </TabsTrigger>
                  <TabsTrigger value="pairs" className="data-[state=active]:bg-[#00E5FF]/15 data-[state=active]:text-[#00E5FF]">
                    Pairs ({pairs.length})
                  </TabsTrigger>
                  <TabsTrigger value="telegram" className="data-[state=active]:bg-[#00E5FF]/15 data-[state=active]:text-[#00E5FF]">
                    Telegram Log
                  </TabsTrigger>
                </TabsList>

                {/* Signals Tab */}
                <TabsContent value="signals" className="mt-4">
                  <Card className="dashboard-card">
                    <CardHeader className="pb-2 flex flex-row items-center justify-between">
                      <CardTitle className="font-chivo text-[#FAFAFA] flex items-center gap-2">
                        <Zap className="h-4 w-4 text-[#00E5FF]" />
                        Recent Signals
                      </CardTitle>
                      <Button 
                        size="sm" 
                        onClick={triggerAnalysis}
                        disabled={loading || !botStatus.running}
                        className="bg-[#00E5FF]/15 hover:bg-[#00E5FF]/25 text-[#00E5FF] border-none"
                        data-testid="analyze-now-btn"
                      >
                        <RefreshCw className="h-3 w-3 mr-1" />
                        Analyze Now
                      </Button>
                    </CardHeader>
                    <CardContent>
                      <ScrollArea className="h-[400px]">
                        <div className="table-container">
                          <Table data-testid="signals-table">
                            <TableHeader>
                              <TableRow className="border-b border-[#ffffff]/10">
                                <TableHead className="text-[#71717A] text-xs uppercase tracking-wider">Pair</TableHead>
                                <TableHead className="text-[#71717A] text-xs uppercase tracking-wider">Direction</TableHead>
                                <TableHead className="text-[#71717A] text-xs uppercase tracking-wider">Entry</TableHead>
                                <TableHead className="text-[#71717A] text-xs uppercase tracking-wider">Conf.</TableHead>
                                <TableHead className="text-[#71717A] text-xs uppercase tracking-wider">Indicators</TableHead>
                                <TableHead className="text-[#71717A] text-xs uppercase tracking-wider">Result</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {signals.length > 0 ? (
                                signals.map((signal) => (
                                  <SignalRow key={signal.id} signal={signal} />
                                ))
                              ) : (
                                <TableRow>
                                  <TableCell colSpan={6} className="text-center text-[#71717A] py-8">
                                    <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-50" />
                                    No signals yet. Start the bot to begin analysis.
                                  </TableCell>
                                </TableRow>
                              )}
                            </TableBody>
                          </Table>
                        </div>
                      </ScrollArea>
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* Pairs Tab */}
                <TabsContent value="pairs" className="mt-4">
                  <Card className="dashboard-card">
                    <CardHeader className="pb-2">
                      <CardTitle className="font-chivo text-[#FAFAFA]">
                        Monitored OTC Pairs
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-7 gap-2" data-testid="pairs-grid">
                        {pairs.map((pair) => (
                          <PairChip 
                            key={pair} 
                            pair={pair} 
                            hasActiveSignal={activePairs.includes(pair)}
                          />
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>

                {/* Telegram Tab */}
                <TabsContent value="telegram" className="mt-4">
                  <Card className="dashboard-card">
                    <CardHeader className="pb-2">
                      <CardTitle className="font-chivo text-[#FAFAFA] flex items-center gap-2">
                        <Send className="h-4 w-4 text-[#00E5FF]" />
                        Telegram Messages
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ScrollArea className="h-[400px]" data-testid="telegram-log">
                        {telegramMessages.length > 0 ? (
                          telegramMessages.map((msg) => (
                            <TelegramMessage key={msg.id} message={msg} />
                          ))
                        ) : (
                          <div className="text-center text-[#71717A] py-8">
                            <Send className="h-8 w-8 mx-auto mb-2 opacity-50" />
                            No Telegram messages yet.
                          </div>
                        )}
                      </ScrollArea>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>

            {/* Right Column - Config */}
            <div className="space-y-6">
              <ConfigPanel config={config} onUpdate={updateConfig} loading={loading} />
              
              {/* Quick Stats */}
              <Card className="dashboard-card">
                <CardHeader className="pb-2">
                  <CardTitle className="font-chivo text-[#FAFAFA] text-sm">Session Stats</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-[#71717A]">Signals Sent</span>
                    <span className="font-mono text-sm text-[#FAFAFA]">{botStatus.signals_sent}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-[#71717A]">Pairs Monitoring</span>
                    <span className="font-mono text-sm text-[#FAFAFA]">{botStatus.pairs_monitoring}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-[#71717A]">Analysis Interval</span>
                    <span className="font-mono text-sm text-[#FAFAFA]">3 min</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-[#71717A]">Timeframe</span>
                    <span className="font-mono text-sm text-[#FAFAFA]">M1</span>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
