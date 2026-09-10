/* Epistree 星空粒子背景（设计文档 §5.4 / §P9）
   慢速漂浮小光点；数量克制（≤60），关闭连线与悬停交互，避免与
   Cytoscape 画布争抢注意力与帧率。CDN 加载失败时静默放弃。 */
document.addEventListener("DOMContentLoaded", function () {
    var tries = 0;
    var timer = setInterval(function () {
        tries++;
        if (window.tsParticles && document.getElementById("particles-bg")) {
            clearInterval(timer);
            window.tsParticles.load({
                id: "particles-bg",
                options: {
                    fpsLimit: 24,
                    background: { color: "transparent" },
                    particles: {
                        number: { value: 35 },
                        color: { value: ["#7cfc90", "#ffd54f", "#4c9aff"] },
                        shape: { type: "circle" },
                        opacity: { value: { min: 0.08, max: 0.35 } },
                        size: { value: { min: 0.5, max: 2.2 } },
                        move: {
                            enable: true,
                            speed: 0.35,
                            direction: "none",
                            random: true,
                            outModes: { default: "out" }
                        },
                        links: { enable: false }
                    },
                    interactivity: {
                        events: { onHover: { enable: false }, onClick: { enable: false } }
                    },
                    detectRetina: false
                }
            });
        } else if (tries > 40) {
            clearInterval(timer);
        }
    }, 250);
});
