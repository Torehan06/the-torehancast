// Dark by default; a saved choice from the toggle wins. Loaded as a blocking
// script in <head> so the page never flashes the other theme. A separate file
// (not inline) so the Content-Security-Policy can stay at script-src 'self'.
try {
  var saved = localStorage.getItem('theme')
  if (saved === 'light' || saved === 'dark') document.documentElement.dataset.theme = saved
} catch (e) {}
