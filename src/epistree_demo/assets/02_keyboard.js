// ESC 退出节点聚焦：转发为隐藏按钮点击，由 Dash 回调清除 faded 状态。
// dash-cytoscape 拿不到 cy 实例，键盘事件只能走 DOM → 隐藏按钮 → 回调。
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  var t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  var btn = document.getElementById('btn-esc');
  if (btn) btn.click();
});
