// 用 Windows application loopback 收指定 process（可包括子 process）播出嘅聲音。
// 輸出 48 kHz、16-bit、stereo PCM：寫入 WAV 檔，或以 raw s16le 寫到 stdout。
//
// 用法：
//   ProcLoopback --pid 22304 --out capture.wav --seconds 10
//   ProcLoopback --name Discord --stdout
//   ProcLoopback --pid 1234 --exclude --out others.wav   （收除咗該 process tree 以外嘅聲音）
//
// 參考：https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/

using System.Diagnostics;
using System.Management;
using System.Runtime.InteropServices;

namespace ProcLoopback;

internal static class Program
{
    const int SampleRate = 48000;
    const int Channels = 2;
    const int BitsPerSample = 16;
    const int BlockAlign = Channels * BitsPerSample / 8;

    static int Main(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        int? pid = null;
        string? name = null;
        string? outPath = null;
        bool toStdout = false;
        bool exclude = false;
        double seconds = 0;

        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--pid": pid = int.Parse(args[++i]); break;
                case "--name": name = args[++i]; break;
                case "--out": outPath = args[++i]; break;
                case "--stdout": toStdout = true; break;
                case "--exclude": exclude = true; break;
                case "--seconds": seconds = double.Parse(args[++i]); break;
                default:
                    Console.Error.WriteLine($"未知參數：{args[i]}");
                    return 2;
            }
        }

        if (name != null) pid = FindRootProcess(name);
        if (pid == null || (outPath == null) == !toStdout)
        {
            Console.Error.WriteLine("用法：ProcLoopback (--pid N | --name Discord) (--out file.wav | --stdout) [--seconds S] [--exclude]");
            return 2;
        }

        Console.Error.WriteLine($"[ProcLoopback] 目標 PID {pid}，模式 {(exclude ? "排除" : "包括")} process tree");

        var stop = new ManualResetEvent(false);
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; stop.Set(); };
        if (seconds > 0) _ = Task.Delay(TimeSpan.FromSeconds(seconds)).ContinueWith(_ => stop.Set());

        Stream sink = toStdout ? Console.OpenStandardOutput() : new FileStream(outPath!, FileMode.Create, FileAccess.Write);
        if (!toStdout) sink.Write(new byte[44]); // WAV header 留位，完成後補寫

        long bytesWritten = 0;
        try
        {
            bytesWritten = Capture(pid.Value, exclude, sink, stop);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[ProcLoopback] 失敗：{ex.Message}");
            return 1;
        }
        finally
        {
            if (!toStdout)
            {
                sink.Seek(0, SeekOrigin.Begin);
                WriteWavHeader(sink, bytesWritten);
            }
            sink.Dispose();
        }

        Console.Error.WriteLine($"[ProcLoopback] 完成，{bytesWritten / (double)(SampleRate * BlockAlign):F2} 秒音訊");
        return 0;
    }

    // 搵名為 name 嘅 process tree 嘅根（parent 唔係同名 process 嗰個）。
    static int FindRootProcess(string name)
    {
        var exe = name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ? name : name + ".exe";
        using var searcher = new ManagementObjectSearcher(
            $"SELECT ProcessId, ParentProcessId FROM Win32_Process WHERE Name = '{exe.Replace("'", "")}'");
        var procs = searcher.Get().Cast<ManagementObject>()
            .Select(m => (Pid: Convert.ToInt32(m["ProcessId"]), Parent: Convert.ToInt32(m["ParentProcessId"])))
            .ToList();
        var pids = procs.Select(p => p.Pid).ToHashSet();
        var roots = procs.Where(p => !pids.Contains(p.Parent)).ToList();
        if (roots.Count != 1)
            throw new InvalidOperationException($"搵到 {roots.Count} 個 {exe} 根 process，請改用 --pid 指定");
        return roots[0].Pid;
    }

    static long Capture(int pid, bool exclude, Stream sink, WaitHandle stop)
    {
        var audioClient = ActivateProcessLoopback(pid, exclude);

        var format = new WaveFormatEx
        {
            wFormatTag = 1, // WAVE_FORMAT_PCM
            nChannels = Channels,
            nSamplesPerSec = SampleRate,
            nAvgBytesPerSec = SampleRate * BlockAlign,
            nBlockAlign = BlockAlign,
            wBitsPerSample = BitsPerSample,
            cbSize = 0,
        };

        const uint AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000;
        const uint AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000;
        const uint AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000;
        const long bufferDuration100ns = 200_000; // 20 ms

        Check(audioClient.Initialize(0, AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
            bufferDuration100ns, 0, ref format, IntPtr.Zero), "IAudioClient.Initialize");

        var captureIid = typeof(IAudioCaptureClient).GUID;
        Check(audioClient.GetService(ref captureIid, out var captureObj), "IAudioClient.GetService");
        var capture = (IAudioCaptureClient)captureObj;

        using var packetReady = new AutoResetEvent(false);
        Check(audioClient.SetEventHandle(packetReady.SafeWaitHandle.DangerousGetHandle()), "IAudioClient.SetEventHandle");
        Check(audioClient.Start(), "IAudioClient.Start");

        long total = 0;
        var buffer = new byte[SampleRate * BlockAlign]; // 最多一秒
        var handles = new WaitHandle[] { packetReady, stop };
        try
        {
            while (WaitHandle.WaitAny(handles) == 0)
            {
                while (true)
                {
                    Check(capture.GetNextPacketSize(out uint packetFrames), "GetNextPacketSize");
                    if (packetFrames == 0) break;

                    Check(capture.GetBuffer(out IntPtr data, out uint frames, out uint flags, out _, out _), "GetBuffer");
                    int bytes = (int)frames * BlockAlign;
                    if (bytes > buffer.Length) buffer = new byte[bytes];

                    const uint AUDCLNT_BUFFERFLAGS_SILENT = 0x2;
                    if ((flags & AUDCLNT_BUFFERFLAGS_SILENT) != 0) Array.Clear(buffer, 0, bytes);
                    else Marshal.Copy(data, buffer, 0, bytes);

                    Check(capture.ReleaseBuffer(frames), "ReleaseBuffer");
                    sink.Write(buffer, 0, bytes);
                    total += bytes;
                }
                sink.Flush();
            }
        }
        finally
        {
            audioClient.Stop();
            Marshal.ReleaseComObject(capture);
            Marshal.ReleaseComObject(audioClient);
        }
        return total;
    }

    static IAudioClient ActivateProcessLoopback(int pid, bool exclude)
    {
        var activationParams = new AudioClientActivationParams
        {
            ActivationType = 1, // AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
            TargetProcessId = (uint)pid,
            ProcessLoopbackMode = exclude ? 1u : 0u, // EXCLUDE / INCLUDE_TARGET_PROCESS_TREE
        };

        int paramsSize = Marshal.SizeOf<AudioClientActivationParams>();
        IntPtr paramsPtr = Marshal.AllocHGlobal(paramsSize);
        IntPtr propVariantPtr = Marshal.AllocHGlobal(Marshal.SizeOf<PropVariantBlob>());
        try
        {
            Marshal.StructureToPtr(activationParams, paramsPtr, false);
            Marshal.StructureToPtr(new PropVariantBlob { vt = 65 /* VT_BLOB */, cbSize = (uint)paramsSize, pBlobData = paramsPtr },
                propVariantPtr, false);

            var handler = new ActivationHandler();
            var audioClientIid = typeof(IAudioClient).GUID;
            Check(NativeMethods.ActivateAudioInterfaceAsync("VAD\\Process_Loopback", ref audioClientIid, propVariantPtr, handler, out _),
                "ActivateAudioInterfaceAsync");

            if (!handler.Done.WaitOne(TimeSpan.FromSeconds(5)))
                throw new TimeoutException("ActivateAudioInterfaceAsync 5 秒內冇完成");
            Check(handler.Result, "啟用 process loopback");
            return (IAudioClient)handler.Interface!;
        }
        finally
        {
            Marshal.FreeHGlobal(propVariantPtr);
            Marshal.FreeHGlobal(paramsPtr);
        }
    }

    static void WriteWavHeader(Stream s, long dataBytes)
    {
        using var w = new BinaryWriter(s, System.Text.Encoding.ASCII, leaveOpen: true);
        w.Write("RIFF"u8);
        w.Write((uint)(36 + dataBytes));
        w.Write("WAVE"u8);
        w.Write("fmt "u8);
        w.Write(16u);
        w.Write((ushort)1);
        w.Write((ushort)Channels);
        w.Write((uint)SampleRate);
        w.Write((uint)(SampleRate * BlockAlign));
        w.Write((ushort)BlockAlign);
        w.Write((ushort)BitsPerSample);
        w.Write("data"u8);
        w.Write((uint)dataBytes);
    }

    static void Check(int hr, string what)
    {
        if (hr < 0) throw new COMException($"{what} 失敗（HRESULT 0x{hr:X8}）", hr);
    }
}

[ComVisible(true)]
[ClassInterface(ClassInterfaceType.None)]
internal sealed class ActivationHandler : IActivateAudioInterfaceCompletionHandler, IAgileObject
{
    public readonly ManualResetEvent Done = new(false);
    public int Result;
    public object? Interface;

    public int ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation)
    {
        int hr = operation.GetActivateResult(out Result, out Interface);
        if (hr < 0) Result = hr;
        Done.Set();
        return 0;
    }
}

internal static class NativeMethods
{
    [DllImport("Mmdevapi.dll", ExactSpelling = true)]
    public static extern int ActivateAudioInterfaceAsync(
        [MarshalAs(UnmanagedType.LPWStr)] string deviceInterfacePath,
        ref Guid riid,
        IntPtr activationParams,
        IActivateAudioInterfaceCompletionHandler completionHandler,
        out IActivateAudioInterfaceAsyncOperation activationOperation);
}

[StructLayout(LayoutKind.Sequential)]
internal struct AudioClientActivationParams
{
    public uint ActivationType;
    public uint TargetProcessId;
    public uint ProcessLoopbackMode;
}

[StructLayout(LayoutKind.Explicit, Size = 24)]
internal struct PropVariantBlob
{
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public uint cbSize;
    [FieldOffset(16)] public IntPtr pBlobData;
}

[StructLayout(LayoutKind.Sequential, Pack = 2)]
internal struct WaveFormatEx
{
    public ushort wFormatTag;
    public ushort nChannels;
    public uint nSamplesPerSec;
    public uint nAvgBytesPerSec;
    public ushort nBlockAlign;
    public ushort wBitsPerSample;
    public ushort cbSize;
}

[ComImport, Guid("41D949AB-9862-444A-80F6-C261334DA5EB"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IActivateAudioInterfaceCompletionHandler
{
    [PreserveSig] int ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation);
}

[ComImport, Guid("72A22D78-CDE4-431D-B8CC-843A71199B6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IActivateAudioInterfaceAsyncOperation
{
    [PreserveSig] int GetActivateResult(out int activateResult, [MarshalAs(UnmanagedType.IUnknown)] out object activatedInterface);
}

[ComImport, Guid("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IAgileObject { }

[ComImport, Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IAudioClient
{
    [PreserveSig] int Initialize(int shareMode, uint streamFlags, long bufferDuration, long periodicity, ref WaveFormatEx format, IntPtr audioSessionGuid);
    [PreserveSig] int GetBufferSize(out uint bufferFrames);
    [PreserveSig] int GetStreamLatency(out long latency);
    [PreserveSig] int GetCurrentPadding(out uint paddingFrames);
    [PreserveSig] int IsFormatSupported(int shareMode, IntPtr format, out IntPtr closestMatch);
    [PreserveSig] int GetMixFormat(out IntPtr format);
    [PreserveSig] int GetDevicePeriod(out long defaultPeriod, out long minimumPeriod);
    [PreserveSig] int Start();
    [PreserveSig] int Stop();
    [PreserveSig] int Reset();
    [PreserveSig] int SetEventHandle(IntPtr eventHandle);
    [PreserveSig] int GetService(ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object service);
}

[ComImport, Guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IAudioCaptureClient
{
    [PreserveSig] int GetBuffer(out IntPtr data, out uint numFramesToRead, out uint flags, out ulong devicePosition, out ulong qpcPosition);
    [PreserveSig] int ReleaseBuffer(uint numFramesRead);
    [PreserveSig] int GetNextPacketSize(out uint numFramesInNextPacket);
}
