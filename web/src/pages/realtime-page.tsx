"use client";

import { useEffect, useState, useRef, useMemo } from "react";
import { Mic, Activity, TrendingUp, Clock } from "lucide-react";
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

const MAX_AUDIO_POINTS = 60;

export function RealtimePage() {
  const [audioData, setAudioData] = useState<AudioData[]>([]);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const audioBuf = useRef<AudioData[]>([]);

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

    // Flush every 1s — average all buffered samples into one smooth point
    const flushInterval = setInterval(() => {
      if (audioBuf.current.length === 0) return;
      const batch = audioBuf.current.splice(0);
      const avg: AudioData = {
        time: batch[batch.length - 1].time,
        device_id: batch[0].device_id,
        amplitude:
          batch.reduce((s, d) => s + d.amplitude, 0) / batch.length,
        peak: batch.reduce((s, d) => s + d.peak, 0) / batch.length,
      };
      setAudioData((prev) => [...prev, avg].slice(-MAX_AUDIO_POINTS));
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
                  tick={{ fontSize: 10 }}
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
                  strokeWidth={2}
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
