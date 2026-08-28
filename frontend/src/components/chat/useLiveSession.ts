"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { openSocket } from "@/lib/realtime";

/**
 * The live session: speech in, speech out, screen sharing, ambient listening.
 *
 * All of it hangs off ONE socket, because it is all one conversation — an
 * utterance like "what's wrong with this?" means nothing without the screen
 * frame that arrived a second earlier, and reassembling that ordering across two
 * transports is the kind of thing that works in testing and fails on a train.
 *
 * WHY THE BROWSER DOES THE SPEECH
 * By default the phone does both recognition and synthesis with the Web Speech
 * API, and the socket only ever carries text. That needs no models, no GPU and
 * no extra containers — which matters when the target user is on a mid-range
 * Android on a metered connection. A server engine (Whisper/Piper) exists behind
 * the same protocol for deployments that configure it.
 *
 * THE THREE THINGS THAT MAKE IT FEEL LIKE TALKING
 *  - **Barge-in.** Speaking while the assistant talks cuts it off immediately.
 *    `SpeechRecognition` keeps running during playback precisely so it can
 *    detect that.
 *  - **Sentences, not paragraphs.** The server sends each sentence as it is
 *    written, so the reply starts while the rest is still being generated.
 *  - **Ambient gating.** In ambient mode the server decides per utterance
 *    whether it was addressed; the mic stays open but the assistant stays quiet.
 */

export type LiveState =
  | "off"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export interface LiveTranscriptEntry {
  id: string;
  who: "user" | "assistant";
  text: string;
  responding?: boolean | null;
  why?: string;
}

/** Minimal shape of the vendor-prefixed SpeechRecognition API. */
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
};

function getRecogniser(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const Ctor =
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  return Ctor ? (new Ctor() as SpeechRecognitionLike) : null;
}

export function speechSupported(): boolean {
  if (typeof window === "undefined") return false;
  const hasStt =
    !!(window as any).SpeechRecognition || !!(window as any).webkitSpeechRecognition;
  return hasStt && "speechSynthesis" in window;
}

let entryId = 0;

export function useLiveSession(projectId: string, language: "sw" | "en") {
  const [state, setState] = useState<LiveState>("off");
  const [ambient, setAmbient] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [transcript, setTranscript] = useState<LiveTranscriptEntry[]>([]);
  const [interim, setInterim] = useState("");
  const [cue, setCue] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ws = useRef<WebSocket | null>(null);
  const recogniser = useRef<SpeechRecognitionLike | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const frameTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastFrame = useRef<string>("");
  /** True while the assistant's own speech is playing — used for barge-in. */
  const speaking = useRef(false);
  const wantOpen = useRef(false);
  const ambientRef = useRef(false);

  const push = useCallback((entry: Omit<LiveTranscriptEntry, "id">) => {
    setTranscript((cur) => [...cur.slice(-40), { id: `e${entryId++}`, ...entry }]);
  }, []);

  const send = useCallback((payload: Record<string, unknown>) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(payload));
    }
  }, []);

  /* ------------------------------------------------------------- speaking */
  const speak = useCallback(
    (text: string) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
      const utter = new SpeechSynthesisUtterance(text);
      // Kiswahili voices are rare; sw-TZ falls back to the platform default
      // rather than failing, which is better than silence.
      utter.lang = language === "sw" ? "sw-TZ" : "en-GB";
      utter.rate = 1.02;
      utter.onstart = () => {
        speaking.current = true;
        setState("speaking");
      };
      utter.onend = () => {
        speaking.current = false;
        setState((s) => (s === "speaking" ? "listening" : s));
      };
      window.speechSynthesis.speak(utter);
    },
    [language],
  );

  const stopSpeaking = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    speaking.current = false;
  }, []);

  /* ---------------------------------------------------------- recognition */
  const startRecognition = useCallback(() => {
    const rec = getRecogniser();
    if (!rec) {
      setError("This browser cannot do speech recognition.");
      setState("error");
      return;
    }
    rec.lang = language === "sw" ? "sw-TZ" : "en-GB";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (event: any) => {
      let finalText = "";
      let interimText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interimText += result[0].transcript;
      }

      // BARGE-IN. Any speech while the assistant is talking cuts it off — the
      // way interrupting a person does. Checked on interim results so it fires
      // on the first syllable rather than at the end of the sentence.
      if ((interimText.trim() || finalText.trim()) && speaking.current) {
        stopSpeaking();
        send({ type: "barge_in" });
      }

      if (interimText) {
        setInterim(interimText);
        send({ type: "transcript", text: interimText, final: false });
      }
      if (finalText.trim()) {
        setInterim("");
        send({ type: "transcript", text: finalText.trim(), final: true });
      }
    };

    rec.onerror = (event: any) => {
      // `no-speech` and `aborted` are routine in ambient mode; only surface the
      // ones a user can act on.
      const code = String(event?.error ?? "");
      if (code === "not-allowed" || code === "service-not-allowed") {
        setError("Microphone permission was denied.");
        setState("error");
        wantOpen.current = false;
      }
    };

    rec.onend = () => {
      // Chrome stops recognition every ~60s and after each result in some
      // versions. Restarting is what makes "always on" actually always on.
      if (wantOpen.current) {
        try {
          rec.start();
        } catch {
          /* already starting */
        }
      }
    };

    recogniser.current = rec;
    try {
      rec.start();
    } catch {
      /* already started */
    }
  }, [language, send, stopSpeaking]);

  /* --------------------------------------------------------------- socket */
  const start = useCallback(
    async (opts: { ambient?: boolean } = {}) => {
      if (ws.current) return;
      setError(null);
      setState("connecting");
      wantOpen.current = true;
      ambientRef.current = !!opts.ambient;
      setAmbient(!!opts.ambient);

      const socket = await openSocket(`/ws/session/${projectId}`);
      if (!socket) {
        setError("Could not open the live session.");
        setState("error");
        wantOpen.current = false;
        return;
      }
      ws.current = socket;

      socket.onopen = () => {
        send({
          type: "hello",
          engine: "browser",
          language,
          ambient: ambientRef.current,
        });
        setState("listening");
        startRecognition();
      };

      socket.onmessage = (event) => {
        let msg: any;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        switch (msg.type) {
          case "heard":
            push({ who: "user", text: msg.text, responding: msg.responding, why: msg.why });
            if (msg.responding) setState("thinking");
            break;
          case "backchannel":
            // A listening noise, not an answer. Shown briefly and spoken at low
            // volume so it reads as attention rather than an interruption.
            setCue(msg.text);
            setTimeout(() => setCue(null), 1400);
            break;
          case "turn_start":
            setState("thinking");
            break;
          case "say":
            push({ who: "assistant", text: msg.text });
            speak(msg.text);
            break;
          case "audio": {
            // Server-synthesised speech.
            push({ who: "assistant", text: msg.text ?? "" });
            const audio = new Audio(`data:${msg.mime ?? "audio/wav"};base64,${msg.data}`);
            speaking.current = true;
            setState("speaking");
            audio.onended = () => {
              speaking.current = false;
              setState((s) => (s === "speaking" ? "listening" : s));
            };
            void audio.play().catch(() => {
              speaking.current = false;
            });
            break;
          }
          case "interrupted":
            stopSpeaking();
            setState("listening");
            break;
          case "turn_end":
            setState("listening");
            break;
          case "error":
            setError(String(msg.message ?? "something went wrong"));
            break;
          default:
            break;
        }
      };

      socket.onclose = () => {
        ws.current = null;
        if (wantOpen.current) {
          setState("error");
          setError("The live session disconnected.");
          wantOpen.current = false;
        } else {
          setState("off");
        }
      };
    },
    [projectId, language, push, send, speak, startRecognition, stopSpeaking],
  );

  const stopScreen = useCallback(() => {
    if (frameTimer.current) clearInterval(frameTimer.current);
    frameTimer.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    lastFrame.current = "";
    setSharing(false);
    send({ type: "screen_stop" });
  }, [send]);

  const stop = useCallback(() => {
    wantOpen.current = false;
    stopSpeaking();
    recogniser.current?.abort();
    recogniser.current = null;
    stopScreen();
    send({ type: "bye" });
    ws.current?.close();
    ws.current = null;
    setState("off");
    setInterim("");
  }, [send, stopScreen, stopSpeaking]);

  /* ---------------------------------------------------------- screen share */
  const startScreen = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getDisplayMedia) {
      setError("This browser cannot share a screen.");
      return;
    }
    try {
      const media = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 1 },
        audio: false,
      });
      stream.current = media;
      setSharing(true);
      // The user can stop sharing from the browser's own control; follow it.
      media.getVideoTracks()[0]?.addEventListener("ended", () => stopScreen());

      const video = document.createElement("video");
      video.srcObject = media;
      video.muted = true;
      await video.play();

      const canvas = document.createElement("canvas");

      frameTimer.current = setInterval(() => {
        if (!stream.current) return;
        // Downscale hard. The assistant needs to see the layout and read large
        // text, not count pixels — and a full-resolution frame every two
        // seconds would saturate a mobile uplink.
        const scale = Math.min(1, 1280 / (video.videoWidth || 1280));
        canvas.width = Math.round((video.videoWidth || 1280) * scale);
        canvas.height = Math.round((video.videoHeight || 720) * scale);
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const data = canvas.toDataURL("image/jpeg", 0.6).split(",")[1] ?? "";

        // Only send when the picture actually changed. A static screen would
        // otherwise stream identical frames forever for no benefit.
        if (data && data !== lastFrame.current) {
          lastFrame.current = data;
          send({ type: "frame", data, at: Date.now() });
        }
      }, 2000);
    } catch {
      setError("Screen sharing was not permitted.");
    }
  }, [send, stopScreen]);

  /* -------------------------------------------------------------- cleanup */
  useEffect(() => {
    return () => {
      wantOpen.current = false;
      recogniser.current?.abort();
      stream.current?.getTracks().forEach((t) => t.stop());
      if (frameTimer.current) clearInterval(frameTimer.current);
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
      ws.current?.close();
    };
  }, []);

  const setAmbientMode = useCallback(
    (on: boolean) => {
      ambientRef.current = on;
      setAmbient(on);
      send({ type: "hello", engine: "browser", language, ambient: on });
    },
    [language, send],
  );

  return {
    state,
    ambient,
    sharing,
    transcript,
    interim,
    cue,
    error,
    start,
    stop,
    setAmbientMode,
    startScreen,
    stopScreen,
    supported: speechSupported(),
  };
}
