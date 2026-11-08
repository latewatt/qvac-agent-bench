// Start the JS SDK's worker and round-trip a heartbeat. No model is loaded.
// Run from a directory where @qvac/sdk is installed. Prints one JSON line.
const timer = setTimeout(() => { console.log(JSON.stringify({ ok: false, error: 'timeout after 60s' })); process.exit(1); }, 60000);
let sdk;
try {
  sdk = await import('@qvac/sdk');
  const reply = await sdk.heartbeat();
  console.log(JSON.stringify({ ok: reply?.type === 'heartbeat', reply: reply?.type }));
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: `${e?.name}: ${e?.message}`.slice(0, 500) }));
  process.exitCode = 1;
} finally {
  try { await sdk?.close(); } catch {}
  clearTimeout(timer);
}
