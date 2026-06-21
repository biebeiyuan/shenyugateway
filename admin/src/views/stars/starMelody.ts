import type { StarItem } from '@/api/stars'
import { rootFromStar } from './starUi'

type AudioContextConstructor = new () => AudioContext

function midiForRoot(root: string): number {
  const semitone: Record<string, number> = {
    C: 0,
    'C#': 1,
    D: 2,
    'D#': 3,
    E: 4,
    F: 5,
    'F#': 6,
    G: 7,
    'G#': 8,
    A: 9,
    'A#': 10,
    B: 11,
  }
  return 60 + (semitone[root] ?? 0)
}

function noteFrequency(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12)
}

function chordIntervals(star: StarItem): number[] {
  const chord = Array.isArray(star.chord_sequence) && star.chord_sequence.length ? star.chord_sequence[0] : star.chord
  const quality = (star.chord_quality || chord || '').toLowerCase()
  if (quality.includes('dim')) return [0, 3, 6]
  if (quality.includes('aug')) return [0, 4, 8]
  if (quality.includes('sus')) return [0, 5, 7]
  if (quality.includes('minor') || quality.includes('min') || /\bm(?!aj)/i.test(chord)) return [0, 3, 7]
  return [0, 4, 7]
}

function chordSequenceForStar(star: StarItem): string[] {
  const sequence = Array.isArray(star.chord_sequence) ? star.chord_sequence.filter(Boolean) : []
  return sequence.length ? sequence : [star.chord || '']
}

function playTone(audio: AudioContext, destination: GainNode, frequency: number, start: number, duration: number, gain = 0.08) {
  const oscillator = audio.createOscillator()
  const envelope = audio.createGain()
  oscillator.type = 'sine'
  oscillator.frequency.setValueAtTime(frequency, start)
  envelope.gain.setValueAtTime(0.0001, start)
  envelope.gain.exponentialRampToValueAtTime(gain, start + 0.035)
  envelope.gain.exponentialRampToValueAtTime(0.0001, start + duration)
  oscillator.connect(envelope)
  envelope.connect(destination)
  oscillator.start(start)
  oscillator.stop(start + duration + 0.05)
}

export async function playConstellationMelody(stars: StarItem[]): Promise<void> {
  if (stars.length < 2) return
  const audioWindow = window as unknown as { AudioContext?: AudioContextConstructor; webkitAudioContext?: AudioContextConstructor }
  const AudioCtor = audioWindow.AudioContext || audioWindow.webkitAudioContext
  if (!AudioCtor) {
    throw new Error('audio_context_unavailable')
  }
  const audio = new AudioCtor()
  const master = audio.createGain()
  master.gain.value = 0.72
  master.connect(audio.destination)
  const start = audio.currentTime + 0.08
  const step = 0.42
  const events = stars.flatMap((star) => chordSequenceForStar(star).map((chordText) => ({ star, chordText })))
  events.forEach(({ star, chordText }, index) => {
    const midi = midiForRoot(rootFromStar({ ...star, chord: chordText, chord_sequence: [] }) || 'C')
    const at = start + index * step
    playTone(audio, master, noteFrequency(midi), at, 0.42, 0.09)
    for (const interval of chordIntervals({ ...star, chord: chordText, chord_sequence: [] })) {
      playTone(audio, master, noteFrequency(midi + interval + 12), at + 0.08, 0.52, 0.035)
    }
  })
  const totalMs = (events.length * step + 1.2) * 1000
  await new Promise((resolve) => window.setTimeout(resolve, totalMs))
  await audio.close()
}
