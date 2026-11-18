"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Room,
  RoomEvent,
  Track,
  RemoteTrack,
  RemoteTrackPublication,
  RemoteParticipant,
  createLocalTracks,
  LocalTrack,
} from "livekit-client";

interface UseLiveKitOptions {
  url: string;
  token: string;
  publishCamera: boolean;
  publishMic: boolean;
}

interface RemoteVideoInfo {
  identity: string;
  track: MediaStreamTrack;
}

export interface RemoteParticipantInfo {
  identity: string;
  name: string;
  canPublish: boolean;
}

export interface CaptionData {
  questionIndex: number;
  text: string;
}

interface UseLiveKitReturn {
  room: Room | null;
  connected: boolean;
  aiAudioTrack: MediaStreamTrack | null;
  candidateAudioTrack: MediaStreamTrack | null;
  interviewerAudioTrack: MediaStreamTrack | null;
  localVideoTrack: MediaStreamTrack | null;
  remoteVideos: RemoteVideoInfo[];
  remoteParticipants: RemoteParticipantInfo[];
  aiSpeaking: boolean;
  candidateSpeaking: boolean;
  interviewerSpeaking: boolean;
  micMuted: boolean;
  caption: CaptionData | null;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  setMicMuted: (muted: boolean) => void;
}

export function useLiveKit(options: UseLiveKitOptions | null): UseLiveKitReturn {
  const roomRef = useRef<Room | null>(null);
  const localAudioTrackRef = useRef<LocalTrack | null>(null);
  const [roomState, setRoomState] = useState<Room | null>(null);
  const [connected, setConnected] = useState(false);
  const [aiAudioTrack, setAiAudioTrack] = useState<MediaStreamTrack | null>(null);
  const [candidateAudioTrack, setCandidateAudioTrack] = useState<MediaStreamTrack | null>(null);
  const [interviewerAudioTrack, setInterviewerAudioTrack] = useState<MediaStreamTrack | null>(null);
  const [localVideoTrack, setLocalVideoTrack] = useState<MediaStreamTrack | null>(null);
  const [remoteVideos, setRemoteVideos] = useState<RemoteVideoInfo[]>([]);
  const [remoteParticipants, setRemoteParticipants] = useState<RemoteParticipantInfo[]>([]);
  const [aiSpeaking, setAiSpeaking] = useState(false);
  const [candidateSpeaking, setCandidateSpeaking] = useState(false);
  const [interviewerSpeaking, setInterviewerSpeaking] = useState(false);
  const [micMuted, setMicMutedState] = useState(true);
  const [caption, setCaption] = useState<CaptionData | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const connect = useCallback(async () => {
    const opts = optionsRef.current;
    if (!opts) return;

    // Disconnect any previous room to prevent competing connections
    const prev = roomRef.current;
    if (prev) {
      try { prev.disconnect(); } catch {}
      roomRef.current = null;
    }

    const room = new Room();
    roomRef.current = room;
    setRoomState(room);

    // Track subscribed — attach all remote audio + track remote video
    room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, pub: RemoteTrackPublication, participant: RemoteParticipant) => {
      if (track.kind === Track.Kind.Audio) {
        const audioEl = track.attach();
        audioEl.setAttribute("autoplay", "true");
        document.body.appendChild(audioEl);

        if (participant.identity.startsWith("suvera-ai")) {
          const ms = track.mediaStream;
          if (ms && ms.getAudioTracks().length > 0) {
            setAiAudioTrack(ms.getAudioTracks()[0]);
          }
        } else if (participant.identity.startsWith("candidate-")) {
          const ms = track.mediaStream;
          if (ms && ms.getAudioTracks().length > 0) {
            setCandidateAudioTrack(ms.getAudioTracks()[0]);
          }
        } else if (participant.identity.startsWith("interviewer-")) {
          const ms = track.mediaStream;
          if (ms && ms.getAudioTracks().length > 0) {
            setInterviewerAudioTrack(ms.getAudioTracks()[0]);
          }
        }
      }

      if (track.kind === Track.Kind.Video) {
        setRemoteVideos((prev) => [
          ...prev.filter((v) => v.identity !== participant.identity),
          { identity: participant.identity, track: track.mediaStreamTrack },
        ]);
      }
    });

    room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack, pub: RemoteTrackPublication, participant: RemoteParticipant) => {
      if (track.kind === Track.Kind.Audio) {
        track.detach().forEach((el) => el.remove());
        if (participant.identity.startsWith("suvera-ai")) {
          setAiAudioTrack(null);
        } else if (participant.identity.startsWith("candidate-")) {
          setCandidateAudioTrack(null);
        } else if (participant.identity.startsWith("interviewer-")) {
          setInterviewerAudioTrack(null);
        }
      }

      if (track.kind === Track.Kind.Video) {
        setRemoteVideos((prev) => prev.filter((v) => v.identity !== participant.identity));
      }
    });

    room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
      setAiSpeaking(speakers.some((p) => p.identity.startsWith("suvera-ai")));
      setCandidateSpeaking(speakers.some((p) => p.identity.startsWith("candidate-")));
      setInterviewerSpeaking(speakers.some((p) => p.identity.startsWith("interviewer-")));
    });

    // Data channel — receive caption from AI bot
    room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg.type === "caption") {
          setCaption({ questionIndex: msg.question_index, text: msg.text });
        } else if (msg.type === "caption_clear") {
          setCaption(null);
        }
      } catch {
        // ignore non-JSON data
      }
    });

    // Track participant connect/disconnect for visibility detection
    room.on(RoomEvent.ParticipantConnected, (participant: RemoteParticipant) => {
      setRemoteParticipants((prev) => [
        ...prev.filter((p) => p.identity !== participant.identity),
        {
          identity: participant.identity,
          name: participant.name || participant.identity,
          canPublish: participant.permissions?.canPublish ?? false,
        },
      ]);
    });

    room.on(RoomEvent.ParticipantDisconnected, (participant: RemoteParticipant) => {
      setRemoteParticipants((prev) => prev.filter((p) => p.identity !== participant.identity));
    });

    room.on(RoomEvent.ParticipantPermissionsChanged, (_prev, participant) => {
      if (participant.identity === room.localParticipant.identity) return;
      setRemoteParticipants((prev) =>
        prev.map((p) =>
          p.identity === participant.identity
            ? { ...p, canPublish: participant.permissions?.canPublish ?? false }
            : p
        )
      );
    });

    room.on(RoomEvent.Disconnected, () => {
      setConnected(false);
      setAiAudioTrack(null);
      setCandidateAudioTrack(null);
      setInterviewerAudioTrack(null);
      setLocalVideoTrack(null);
      setRemoteVideos([]);
      setRemoteParticipants([]);
      setCandidateSpeaking(false);
      setInterviewerSpeaking(false);
      setCaption(null);
    });

    await room.connect(opts.url, opts.token);
    setConnected(true);

    // Ensure audio playback is allowed (browser autoplay policy)
    try { await room.startAudio(); } catch {}

    // Seed already-connected remote participants
    const existing: RemoteParticipantInfo[] = [];
    room.remoteParticipants.forEach((p) => {
      existing.push({
        identity: p.identity,
        name: p.name || p.identity,
        canPublish: p.permissions?.canPublish ?? false,
      });
    });
    setRemoteParticipants(existing);

    // Publish local tracks — wrapped in try/catch so a mic/camera failure
    // doesn't break the room connection (candidate can still hear AI)
    const trackOptions: { audio: boolean; video: boolean } = {
      audio: opts.publishMic,
      video: opts.publishCamera,
    };

    if (trackOptions.audio || trackOptions.video) {
      try {
        const tracks = await createLocalTracks(trackOptions);
        for (const track of tracks) {
          await room.localParticipant.publishTrack(track);
          if (track.kind === Track.Kind.Video) {
            setLocalVideoTrack(track.mediaStreamTrack);
          }
          if (track.kind === Track.Kind.Audio) {
            localAudioTrackRef.current = track;
            await track.mute();
            setMicMutedState(true);
          }
        }
      } catch (err) {
        console.warn("Failed to publish local tracks (mic/camera may be unavailable):", err);
      }
    }
  }, []);

  const disconnect = useCallback(async () => {
    const room = roomRef.current;
    if (room) {
      // Stop all local tracks to release hardware (mic/camera)
      room.localParticipant.audioTrackPublications.forEach((pub) => {
        pub.track?.stop();
      });
      room.localParticipant.videoTrackPublications.forEach((pub) => {
        pub.track?.stop();
      });
      room.disconnect();
      roomRef.current = null;
    }
    localAudioTrackRef.current = null;
    setRoomState(null);
    setConnected(false);
    setAiAudioTrack(null);
    setCandidateAudioTrack(null);
    setInterviewerAudioTrack(null);
    setLocalVideoTrack(null);
    setRemoteVideos([]);
    setRemoteParticipants([]);
    setCandidateSpeaking(false);
    setInterviewerSpeaking(false);
    setCaption(null);
  }, []);

  const setMicMuted = useCallback((muted: boolean) => {
    const track = localAudioTrackRef.current;
    if (!track) return;
    if (muted) {
      track.mute();
    } else {
      track.unmute();
    }
    setMicMutedState(muted);
  }, []);

  // Cleanup on unmount — stop all tracks to release hardware
  useEffect(() => {
    return () => {
      const room = roomRef.current;
      if (room) {
        room.localParticipant.audioTrackPublications.forEach((pub) => {
          pub.track?.stop();
        });
        room.localParticipant.videoTrackPublications.forEach((pub) => {
          pub.track?.stop();
        });
        room.disconnect();
      }
    };
  }, []);

  return {
    room: roomState,
    connected,
    aiAudioTrack,
    candidateAudioTrack,
    interviewerAudioTrack,
    localVideoTrack,
    remoteVideos,
    remoteParticipants,
    aiSpeaking,
    candidateSpeaking,
    interviewerSpeaking,
    micMuted,
    caption,
    connect,
    disconnect,
    setMicMuted,
  };
}
