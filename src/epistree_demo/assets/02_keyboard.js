// ESC 退出节点聚焦 / 点击背景空白区域即时恢复全景
function getCytoscapeInstance() {
  var cy = window.cy || window['cytoscape-graph'];
  if (!cy) {
    var container = document.getElementById('cytoscape-graph');
    if (container && container._cyreg && container._cyreg.cy) {
      cy = container._cyreg.cy;
    }
  }
  return cy;
}

function resetAllFocus() {
  var cy = getCytoscapeInstance();
  if (cy && cy.elements) {
    try {
      cy.nodes().unselect();
      cy.edges().unselect();
      cy.elements().removeClass('highlighted');
      cy.elements().removeClass('faded');
    } catch (e) {
      console.warn('Error clearing cytoscape focus:', e);
    }
  }
  var btn = document.getElementById('btn-reset-focus') || document.getElementById('btn-esc');
  if (btn) {
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  }
}

// 键盘 ESC 退出聚焦
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  var t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  resetAllFocus();
});

// 点击面板上的退出按钮即刻前端清除高光
document.addEventListener('click', function (e) {
  var t = e.target;
  if (t && (t.id === 'btn-unfocus-panel' || t.id === 'btn-reset-focus' || t.closest('#btn-unfocus-panel') || t.closest('#btn-reset-focus'))) {
    var cy = getCytoscapeInstance();
    if (cy && cy.elements) {
      cy.nodes().unselect();
      cy.edges().unselect();
      cy.elements().removeClass('highlighted');
      cy.elements().removeClass('faded');
    }
  }
});

// 监听 Cytoscape 画布空白背景点击（空击）及边点击，瞬间恢复全景，花果叶完好保留
function attachCytoscapeBackgroundTap() {
  var cy = getCytoscapeInstance();
  if (cy && cy.on && !cy._bgTapAttached) {
    cy._bgTapAttached = true;
    cy.on('tap', function (evt) {
      // evt.target === cy: 点中空白画布；evt.target.isEdge(): 点中非节点边干 -> 均视为空击重置
      if (evt.target === cy || (evt.target && evt.target.isEdge && evt.target.isEdge())) {
        resetAllFocus();
      }
    });
  }
}

setInterval(attachCytoscapeBackgroundTap, 400);
