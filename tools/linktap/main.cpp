// linktap: receive one Ableton Link Audio channel and write it to stdout as mono
// float32 little-endian PCM. The sample rate is printed on stderr as "rate=<hz>"
// before any audio (the same contract as livetap). Needs a Link Audio sender on
// this machine or network, e.g. Ableton Live 12.4+ with Link Audio enabled.
//
//   linktap [text]        receive the first channel whose "peer/channel" name contains text
//   linktap --list        print the channels on offer for a few seconds, then exit
//   linktap --send-tone   offer a channel "tone" carrying a 440 Hz sine (for testing)
//
// Built on the Ableton Link SDK (GPL-2.0-or-later), so this helper is GPL too.

#include <ableton/LinkAudio.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

namespace
{
std::atomic<bool> running{true};

std::string lower(std::string s)
{
  std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
  return s;
}

int sendTone(ableton::LinkAudio& link)
{
  const uint32_t rate = 48000;
  const size_t frames = 480; // 10 ms
  ableton::LinkAudioSink sink(link, "tone", frames);
  std::cerr << "sending 440 Hz on channel 'tone'" << std::endl;
  double phase = 0.;
  auto next = std::chrono::steady_clock::now();
  while (running)
  {
    {
      auto buffer = ableton::LinkAudioSink::BufferHandle(sink);
      if (buffer)
      {
        for (size_t i = 0; i < frames; ++i)
        {
          buffer.samples[i] = static_cast<int16_t>(8000. * std::sin(phase));
          phase += 2. * M_PI * 440. / rate;
        }
        const auto state = link.captureAppSessionState();
        buffer.commit(state, state.beatAtTime(link.clock().micros(), 4.), 4., frames, 1, rate);
      }
    }
    next += std::chrono::milliseconds(10);
    std::this_thread::sleep_until(next);
  }
  return 0;
}
} // namespace

int main(int argc, char** argv)
{
  const std::string arg = argc > 1 ? argv[1] : "";
  std::signal(SIGINT, [](int) { running = false; });
  std::signal(SIGTERM, [](int) { running = false; });
  std::signal(SIGPIPE, SIG_IGN);

  ableton::LinkAudio link(120., arg == "--send-tone" ? "linktap test" : "ElfJamAlong");
  link.enable(true);
  link.enableLinkAudio(true);

  if (arg == "--send-tone")
  {
    return sendTone(link);
  }

  const bool listOnly = arg == "--list";
  const std::string wanted = listOnly ? "" : lower(arg);
  const auto started = std::chrono::steady_clock::now();
  const auto waited = [&] {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
  };

  if (listOnly)
  {
    std::this_thread::sleep_for(std::chrono::seconds(3));
    const auto channels = link.channels();
    for (const auto& c : channels)
    {
      std::cout << c.peerName << "/" << c.name << std::endl;
    }
    if (channels.empty())
    {
      std::cerr << "linktap: no Link Audio channels found" << std::endl;
    }
    return channels.empty() ? 1 : 0;
  }

  // Wait for a matching channel to appear.
  ableton::ChannelId id{};
  bool found = false;
  while (running && !found)
  {
    for (const auto& c : link.channels())
    {
      const auto label = c.peerName + "/" + c.name;
      if (wanted.empty() || lower(label).find(wanted) != std::string::npos)
      {
        id = c.id;
        found = true;
        std::cerr << "channel=" << label << std::endl;
        break;
      }
    }
    if (!found)
    {
      if (waited() > 10.)
      {
        std::cerr << "linktap: no Link Audio channel"
                  << (wanted.empty() ? "" : " matching '" + arg + "'")
                  << ". Is Link Audio enabled in the sending app?" << std::endl;
        return 1;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
  }
  if (!found)
  {
    return 1;
  }

  std::atomic<bool> announced{false};
  std::vector<float> mono;
  ableton::LinkAudioSource source(
    link, id, [&](ableton::LinkAudioSource::BufferHandle buffer) {
      const auto& info = buffer.info;
      if (info.numFrames == 0 || info.numChannels == 0)
      {
        return;
      }
      if (!announced.exchange(true))
      {
        std::cerr << "rate=" << info.sampleRate << std::endl;
      }
      mono.resize(info.numFrames);
      const float scale = 1.f / (32768.f * static_cast<float>(info.numChannels));
      for (size_t i = 0; i < info.numFrames; ++i)
      {
        int32_t sum = 0;
        for (size_t c = 0; c < info.numChannels; ++c)
        {
          sum += buffer.samples[i * info.numChannels + c];
        }
        mono[i] = static_cast<float>(sum) * scale;
      }
      if (std::fwrite(mono.data(), sizeof(float), mono.size(), stdout) < mono.size())
      {
        running = false; // the reader went away
      }
      std::fflush(stdout);
    });

  while (running)
  {
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
  }
  return 0;
}
