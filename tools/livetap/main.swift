// livetap: capture one app's audio output (no loopback driver) and write it to
// stdout as mono float32 little-endian PCM. The sample rate is printed on stderr
// as "rate=<hz>" before any audio. Needs macOS 14.4+.
//
//   livetap [bundle-id]        default: com.ableton.live

import AppKit
import AudioToolbox
import CoreAudio
import Foundation

func say(_ text: String) {
    FileHandle.standardError.write((text + "\n").data(using: .utf8)!)
}

func fail(_ text: String, _ status: OSStatus = 0) -> Never {
    say("livetap: " + text + (status != 0 ? " (OSStatus \(status))" : ""))
    exit(1)
}

func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                               mElement: kAudioObjectPropertyElementMain)
}

let system = AudioObjectID(kAudioObjectSystemObject)
let bundleID = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "com.ableton.live"

guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first else {
    fail("\(bundleID) is not running")
}

// The app's Core Audio process object (exists once the app has opened audio).
var pid = app.processIdentifier
var processObject = AudioObjectID(kAudioObjectUnknown)
var size = UInt32(MemoryLayout<AudioObjectID>.size)
var translate = address(kAudioHardwarePropertyTranslatePIDToProcessObject)
var status = AudioObjectGetPropertyData(system, &translate, UInt32(MemoryLayout<pid_t>.size), &pid,
                                        &size, &processObject)
guard status == noErr, processObject != kAudioObjectUnknown else {
    fail("\(bundleID) has no audio process yet; is its audio engine on?", status)
}

// A private, unmuted, mono tap of just that process.
let tapDescription = CATapDescription(monoMixdownOfProcesses: [processObject])
tapDescription.uuid = UUID()
tapDescription.name = "JamAlong tap"
tapDescription.isPrivate = true
tapDescription.muteBehavior = .unmuted
var tapID = AudioObjectID(kAudioObjectUnknown)
status = AudioHardwareCreateProcessTap(tapDescription, &tapID)
guard status == noErr else { fail("could not create the tap; audio capture permission may be denied", status) }

var format = AudioStreamBasicDescription()
size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
var formatAddress = address(kAudioTapPropertyFormat)
status = AudioObjectGetPropertyData(tapID, &formatAddress, 0, nil, &size, &format)
guard status == noErr else { fail("could not read the tap format", status) }

// Taps are read through an aggregate device; the default output device clocks it.
var outputDevice = AudioObjectID(kAudioObjectUnknown)
size = UInt32(MemoryLayout<AudioObjectID>.size)
var outputAddress = address(kAudioHardwarePropertyDefaultSystemOutputDevice)
status = AudioObjectGetPropertyData(system, &outputAddress, 0, nil, &size, &outputDevice)
guard status == noErr else { fail("no default output device", status) }
var outputUID: Unmanaged<CFString>?
size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
var uidAddress = address(kAudioDevicePropertyDeviceUID)
status = AudioObjectGetPropertyData(outputDevice, &uidAddress, 0, nil, &size, &outputUID)
guard status == noErr, let uid = outputUID?.takeRetainedValue() as String? else {
    fail("could not read the output device UID", status)
}

let aggregate: [String: Any] = [
    kAudioAggregateDeviceNameKey: "JamAlong tap",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceMainSubDeviceKey: uid,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: uid]],
    kAudioAggregateDeviceTapListKey: [[
        kAudioSubTapDriftCompensationKey: true,
        kAudioSubTapUIDKey: tapDescription.uuid.uuidString,
    ]],
]
var aggregateID = AudioObjectID(kAudioObjectUnknown)
status = AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID)
guard status == noErr else { fail("could not create the capture device", status) }

let isFloat = format.mFormatFlags & kAudioFormatFlagIsFloat != 0
let interleaved = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved == 0
guard isFloat, format.mBitsPerChannel == 32 else { fail("unexpected tap sample format") }
let channels = Int(format.mChannelsPerFrame)
say("rate=\(Int(format.mSampleRate))")

var mono = [Float](repeating: 0, count: 8192)
var ioProc: AudioDeviceIOProcID?
status = AudioDeviceCreateIOProcIDWithBlock(&ioProc, aggregateID, DispatchQueue(label: "livetap.io")) {
    _, input, _, _, _ in
    let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
    guard let first = buffers.first, let data = first.mData else { return }
    let perBuffer = interleaved ? channels : 1
    let frames = Int(first.mDataByteSize) / (4 * max(perBuffer, 1))
    if frames == 0 { return }
    if mono.count < frames { mono = [Float](repeating: 0, count: frames) }
    for i in 0..<frames { mono[i] = 0 }
    var sources = 0
    if interleaved {
        let samples = data.assumingMemoryBound(to: Float.self)
        for c in 0..<perBuffer {
            for i in 0..<frames { mono[i] += samples[i * perBuffer + c] }
            sources += 1
        }
    } else {
        for buffer in buffers {
            guard let d = buffer.mData else { continue }
            let samples = d.assumingMemoryBound(to: Float.self)
            let n = min(frames, Int(buffer.mDataByteSize) / 4)
            for i in 0..<n { mono[i] += samples[i] }
            sources += 1
        }
    }
    if sources > 1 {
        let scale = 1 / Float(sources)
        for i in 0..<frames { mono[i] *= scale }
    }
    mono.withUnsafeBufferPointer { p in
        if fwrite(p.baseAddress, 4, frames, stdout) < frames { exit(0) }  // reader went away
    }
    fflush(stdout)
}
guard status == noErr, let ioProc else { fail("could not attach to the capture device", status) }

func cleanup() {
    AudioDeviceStop(aggregateID, ioProc)
    AudioDeviceDestroyIOProcID(aggregateID, ioProc)
    AudioHardwareDestroyAggregateDevice(aggregateID)
    AudioHardwareDestroyProcessTap(tapID)
}

signal(SIGPIPE, SIG_IGN)
var sources: [DispatchSourceSignal] = []
for sig in [SIGINT, SIGTERM] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { cleanup(); exit(0) }
    source.resume()
    sources.append(source)
}

status = AudioDeviceStart(aggregateID, ioProc)
guard status == noErr else { cleanup(); fail("could not start capturing", status) }
dispatchMain()
