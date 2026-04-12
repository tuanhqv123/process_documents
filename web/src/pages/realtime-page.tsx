"use client";

import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { Mic, Activity, TrendingUp, Clock, Volume2, VolumeX } from "lucide-react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  LabelList,
  Tooltip,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
interface AudioData {
  time: string;
  device_id: string;
  amplitude: number;
  peak: number;
}

interface Transcript {
  time: string;
  device_id: string;
  text: string;
}

const MAX_AUDIO_POINTS = 80;


export function RealtimePage() {
  const [audioData, setAudioData] = useState<AudioData[]>([]);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const audioBuf = useRef<AudioData[]>([]);
  const emaRef = useRef<number>(0);

  // Live audio playback — server sends pre-cleaned PCM (bandpass + gated)
  const [playback, setPlayback] = useState(false);
  const playbackRef = useRef(false);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const chainRef = useRef<AudioNode | null>(null);
  const nextTimeRef = useRef(0);
  const pcmAccRef = useRef<Int16Array[]>([]);
  const pcmAccLen = useRef(0);
  const audioWsRef = useRef<WebSocket | null>(null);

  // Flush accumulated PCM as one AudioBuffer — browser resamples 16k→native natively
  const flushPcm = useCallback((ctx: AudioContext, chain: AudioNode) => {
    const ACC = 4000; // 250ms @ 16kHz
    if (pcmAccLen.current < ACC) return;
    const combined = new Int16Array(pcmAccLen.current);
    let off = 0;
    for (const c of pcmAccRef.current) { combined.set(c, off); off += c.length; }
    pcmAccRef.current = [];
    pcmAccLen.current = 0;

    const f32 = new Float32Array(combined.length);
    for (let i = 0; i < combined.length; i++) f32[i] = combined[i] / 32768;

    const buf = ctx.createBuffer(1, f32.length, 16000);
    buf.copyToChannel(f32, 0);

    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(chain);

    const now = ctx.currentTime;
    if (nextTimeRef.current < now + 0.2) nextTimeRef.current = now + 0.2;
    src.start(nextTimeRef.current);
    nextTimeRef.current += buf.duration;
  }, []);

  const togglePlayback = useCallback(async () => {
    const next = !playbackRef.current;
    playbackRef.current = next;
    setPlayback(next);

    if (next) {
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      nextTimeRef.current = 0;
      pcmAccRef.current = [];
      pcmAccLen.current = 0;

      // Audio arrives pre-cleaned from server (WebRTC NS)
      // Just a light peak limiter here
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -12;
      comp.knee.value = 6;
      comp.ratio.value = 4;
      comp.attack.value = 0.003;
      comp.release.value = 0.25;
      comp.connect(ctx.destination);
      chainRef.current = comp;

      const base = (import.meta.env.VITE_API_URL || window.location.origin)
        .replace(/^https/, "wss").replace(/^http/, "ws");
      const ws = new WebSocket(`${base}/ws/audio-monitor`);
      ws.binaryType = "arraybuffer";
      ws.onmessage = (ev) => {
        const ctx = audioCtxRef.current;
        const chain = chainRef.current;
        if (!ctx || !chain || !playbackRef.current) return;
        const int16 = new Int16Array(ev.data as ArrayBuffer);
        pcmAccRef.current.push(int16);
        pcmAccLen.current += int16.length;
        flushPcm(ctx, chain);
      };
      ws.onclose = () => { if (playbackRef.current) audioWsRef.current = null; };
      audioWsRef.current = ws;
    } else {
      audioWsRef.current?.close();
      audioWsRef.current = null;
      chainRef.current = null;
      audioCtxRef.current?.close();
      audioCtxRef.current = null;
    }
  }, [flushPcm]);

  // Timeline: group transcripts by hour for last 12 hours
  const timelineData = useMemo(() => {
    const now = new Date();
    const hours: { hour: string; count: number }[] = [];
    for (let i = 11; i >= 0; i--) {
      const h = new Date(now.getTime() - i * 3600000);
      const label = h.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
      const hourStart = new Date(h);
      hourStart.setMinutes(0, 0, 0);
      const hourEnd = new Date(hourStart.getTime() + 3600000);
      const count = transcripts.filter((t) => {
        const d = new Date(t.time);
        return d >= hourStart && d < hourEnd;
      }).length;
      hours.push({ hour: label, count });
    }
    return hours;
  }, [transcripts]);

  useEffect(() => {
    const sseUrl = `${import.meta.env.VITE_API_URL || ""}/api/realtime/stream`;
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      es = new EventSource(sseUrl);

      es.addEventListener("audio", (event) => {
        try {
          const d = JSON.parse(event.data);
          audioBuf.current.push({
            time: new Date(d.time).toLocaleTimeString(),
            device_id: d.device_id,
            amplitude: d.amplitude,
            peak: d.peak,
          });
        } catch {}
      });

      es.addEventListener("transcript", (event) => {
        try {
          const d = JSON.parse(event.data);
          setTranscripts((prev) =>
            [
              {
                time: d.time,
                device_id: d.device_id,
                text: d.text,
              },
              ...prev,
            ].slice(0, 100),
          );
        } catch {}
      });


      es.onerror = () => {
        es?.close();
        reconnectTimer = setTimeout(connect, 3000);
      };
    }

    connect();

    // Flush every 1s — matches server SSE publish rate.
    // Each SSE event = 1 averaged data point, so just push directly.
    const flushInterval = setInterval(() => {
      if (audioBuf.current.length === 0) return;
      const batch = audioBuf.current.splice(0);
      // Take the latest SSE point (already averaged on server)
      const last = batch[batch.length - 1];
      setAudioData((prev) => [...prev, last].slice(-MAX_AUDIO_POINTS));
    }, 1000);

    return () => {
      es?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearInterval(flushInterval);
    };
  }, []);

  return (
    <div className="flex flex-col h-full p-6 gap-4 overflow-y-auto">
      <Card className="shrink-0">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Audio Amplitude
            <button
              onClick={togglePlayback}
              className={`ml-auto flex items-center gap-1 px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                playback
                  ? "bg-green-500/20 text-green-400 hover:bg-green-500/30"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
              title={playback ? "Stop listening" : "Hear live audio"}
            >
              {playback ? <Volume2 className="h-3 w-3" /> : <VolumeX className="h-3 w-3" />}
              {playback ? "Listening" : "Hear audio"}
            </button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {audioData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={audioData}>
                <defs>
                  <linearGradient
                    id="colorAmplitude"
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop
                      offset="5%"
                      stopColor="#22c55e"
                      stopOpacity={0.8}
                    />
                    <stop
                      offset="95%"
                      stopColor="#22c55e"
                      stopOpacity={0.1}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                <XAxis
                  dataKey="time"
                  tick={false}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[0, 0.25]}
                  tick={{ fontSize: 10 }}
                  tickFormatter={(v: number) =>
                    v === 0 ? "0 dB" : `${Math.round(20 * Math.log10(v))} dB`
                  }
                />
                <Area
                  type="basis"
                  dataKey="amplitude"
                  stroke="#22c55e"
                  fillOpacity={1}
                  fill="url(#colorAmplitude)"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[280px] flex items-center justify-center text-muted-foreground">
              Waiting for audio data from ESP32...
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 shrink-0">
        <Card className="flex flex-col h-[400px]">
          <CardHeader className="pb-2 shrink-0">
            <CardTitle className="text-lg flex items-center gap-2">
              <Mic className="h-4 w-4" />
              Speech to Text
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 min-h-0 overflow-hidden p-0">
            <ScrollArea className="h-full p-4" ref={scrollRef}>
              {transcripts.length > 0 ? (
                <div className="space-y-3">
                  {transcripts.map((t, i) => (
                    <div key={i} className="border-b pb-2 last:border-0">
                      <div className="text-xs text-muted-foreground mb-1">
                        {new Date(t.time).toLocaleTimeString()}
                      </div>
                      <div className="text-sm">{t.text}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center text-muted-foreground py-8">
                  No transcripts yet. Upload audio or start speaking to ESP32!
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        <Card className="flex flex-col h-[400px]">
          <CardHeader className="pb-2 shrink-0">
            <CardTitle className="text-lg flex items-center gap-2">
              <TrendingUp className="h-4 w-4" />
              Word Frequency
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 min-h-0">
            {transcripts.length > 0 &&
            getWordFrequency(transcripts).length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={getWordFrequency(transcripts)}
                  layout="vertical"
                  margin={{ right: 60 }}
                >
                  <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} />
                  <YAxis
                    dataKey="word"
                    type="category"
                    tick={{ fontSize: 10 }}
                    width={60}
                  />
                  <Bar dataKey="count" fill="#8b5cf6" radius={4}>
                    <LabelList
                      dataKey="count"
                      position="right"
                      offset={8}
                      fontSize={10}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-muted-foreground">
                No word data yet
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Timeline — transcripts per hour, last 12 hours */}
      <Card className="shrink-0">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Transcript Timeline
            <span className="text-xs font-normal text-muted-foreground ml-2">
              Last 12 hours
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={timelineData}>
              <defs>
                <linearGradient
                  id="colorTimeline"
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.9} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.3} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis dataKey="hour" tick={{ fontSize: 10 }} />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 10 }}
                label={{
                  value: "transcripts",
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 10, fill: "#888" },
                }}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 8,
                }}
                formatter={(value: number) => [value, "Transcripts"]}
              />
              <Bar
                dataKey="count"
                fill="url(#colorTimeline)"
                radius={[4, 4, 0, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}

function getWordFrequency(transcripts: Transcript[]) {
  const wordCounts: Record<string, number> = {};
  transcripts.forEach((t) => {
    const words = t.text
      .toLowerCase()
      .split(/\s+/)
      .filter((w) => w.length > 2);
    words.forEach((word) => {
      wordCounts[word] = (wordCounts[word] || 0) + 1;
    });
  });
  return Object.entries(wordCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([word, count]) => ({ word, count }));
}
