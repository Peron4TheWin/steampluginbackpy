import json
import requests
import sys
from websocket import create_connection

PERON_JS = r"""
(function() {
    if (document.getElementById('peron-tab')) return;

    function waitFor(sel, cb, max) {
        max = max || 50;
        var n = 0;
        function check() {
            var el = document.querySelector(sel);
            if (el) { cb(el); return; }
            if (++n < max) setTimeout(check, 300);
        }
        check();
    }

    waitFor('[role="tablist"]', function(tablist) {
        var appId = (location.href.match(/\/app\/(\d+)/) || [])[1]
                 || (location.search.match(/appid=(\d+)/i) || [])[1];
        if (!appId) {
            var m = document.body.innerHTML.match(/\/app\/(\d+)\/properties/);
            appId = m ? m[1] : null;
        }
        if (!appId) { console.log('[Peron] Could not find appId'); return; }

        // ── Clone a tab button ──
        var tpl = tablist.querySelector('._1-vlriAtKYDViAEunue4VO');
        if (!tpl) return;

        var peronTab = tpl.cloneNode(true);
        peronTab.id = 'peron-tab';
        peronTab.className = tpl.className.replace(/_2DpXjzK3WWsOtUWUrcuOG7/g, '');
        peronTab.setAttribute('aria-selected', 'false');
        var label = peronTab.querySelector('._2PPbMrzl8PKBwpkjYs9b0i');
        if (label) label.textContent = 'Peron';

        // ── Content panel ──
        var panel = document.createElement('div');
        panel.id = 'peron-content';
        panel.className = 'DialogContent _DialogLayout CFTLX2wIKOK3hNV-fS7_V';
        panel.setAttribute('role', 'tabpanel');
        panel.style.display = 'none';

        panel.innerHTML =
            '<div class="DialogContent_InnerWidth">' +
                '<div role="heading" aria-level="2" class="DialogHeader">Peron</div>' +
                '<div class="DialogBody">' +
                    // ── FIXES ──
                    '<div class="DialogControlsSection">' +
                        '<div aria-level="3" role="heading" class="SettingsDialogSubHeader">Fixes</div>' +
                        '<div style="display:flex; gap:8px; align-items:center; margin-top:10px;">' +
                            '<select id="peron-fixes-dd" class="DialogInput DialogInputPlaceholder DialogTextInputBase Focusable" style="flex:1; height:36px; background:#316282; color:#c6d4df; border:1px solid #4c6b22; border-radius:2px; padding:0 8px;">' +
                                '<option value="">-- Select a fix --</option>' +
                                '<option value="fps_unlock">FPS Unlock</option>' +
                                '<option value="skip_intro">Skip Intro</option>' +
                                '<option value="fov_mod">FOV Mod</option>' +
                                '<option value="packet_priority">Network Priority</option>' +
                            '</select>' +
                            '<a id="peron-fixes-apply" class="btnv6_blue_hoverfade btn_medium" href="#"><span>Apply</span></a>' +
                        '</div>' +
                        '<div id="peron-fixes-status" style="color:#8f98a0; font-size:12px; margin-top:6px;"></div>' +
                    '</div>' +
                    // ── DENUVO ──
                    '<div class="DialogControlsSection" style="margin-top:28px;">' +
                        '<div aria-level="3" role="heading" class="SettingsDialogSubHeader">Denuvo</div>' +
                        '<div style="display:flex; justify-content:center; margin-top:16px;">' +
                            '<div style="background:rgba(27,40,56,0.96); border:2px solid #4c6b22; border-radius:6px; padding:22px 28px; text-align:center; max-width:340px; width:100%;">' +
                                '<div style="color:#c6d4df; font-size:15px; font-weight:600; margin-bottom:6px;">Denuvo Token</div>' +
                                '<div style="color:#8f98a0; font-size:12px; margin-bottom:10px;">Manage Denuvo activation for ' + (appId) + '</div>' +
                                '<div style="position:relative;">' +
                                    '<textarea id="peron-denuvo-input" placeholder="Paste Denuvo token here..." spellcheck="false" style="width:100%;box-sizing:border-box;background:#316282;border:1px solid #4c6b22;color:#c6d4df;padding:8px 32px 8px 8px;border-radius:2px;font-size:12px;font-family:monospace;resize:none;min-height:60px;margin-bottom:10px;"></textarea>' +
                                    '<a id="peron-denuvo-copy" href="#" title="Copy to clipboard" style="position:absolute;top:6px;right:6px;display:flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:3px;background:#1b2838;border:1px solid #4c6b22;color:#8f98a0;text-decoration:none;font-size:13px;">' +
                                        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
                                    '</a>' +
                                '</div>' +
                                '<div style="display:flex; gap:8px; justify-content:center;">' +
                                    '<a id="peron-denuvo-get" class="btnv6_blue_hoverfade btn_medium" href="#"><span>Get</span></a>' +
                                    '<a id="peron-denuvo-apply" class="btnv6_white_transparent btn_medium" href="#"><span>Apply</span></a>' +
                                '</div>' +
                                '<div id="peron-denuvo-status" style="color:#8f98a0; font-size:12px; margin-top:10px; min-height:16px;"></div>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        tablist.appendChild(peronTab);
        var contentArea = document.querySelector('.DialogContentTransition');
        if (contentArea) contentArea.appendChild(panel);

        // ── Getter helpers ──
        function allTabs()   { return tablist.querySelectorAll('._1-vlriAtKYDViAEunue4VO'); }
        function allPanels() { return document.querySelectorAll('.DialogContent._DialogLayout'); }

        function selectPeron() {
            allTabs().forEach(function(t) {
                t.classList.remove('_2DpXjzK3WWsOtUWUrcuOG7');
                t.setAttribute('aria-selected', 'false');
            });
            peronTab.classList.add('_2DpXjzK3WWsOtUWUrcuOG7');
            peronTab.setAttribute('aria-selected', 'true');
            allPanels().forEach(function(c) { c.style.display = 'none'; });
            panel.style.display = '';
        }

        peronTab.addEventListener('click', selectPeron);

        // ── Whenever any native tab gets selected, hide our panel ──
        var obs = new MutationObserver(function(ml) {
            ml.forEach(function(m) {
                if (m.type === 'attributes' && m.attributeName === 'class') {
                    var sel = tablist.querySelector('._1-vlriAtKYDViAEunue4VO._2DpXjzK3WWsOtUWUrcuOG7');
                    if (sel && sel.id !== 'peron-tab' && panel.style.display !== 'none') {
                        panel.style.display = 'none';
                        // Unhide native panels that React is managing
                        allPanels().forEach(function(c) {
                            if (c.id !== 'peron-content') c.style.display = '';
                        });
                    }
                }
            });
        });
        obs.observe(tablist, { attributes: true, subtree: true, attributeFilter: ['class'] });

        // ── Load fixes on inject ──
        fetch('http://127.0.0.1:3000/fixes/' + appId)
            .then(function(r) { return r.json().catch(function() { return []; }); })
            .then(function(fixes) {
                var dd = document.getElementById('peron-fixes-dd');
                dd.innerHTML = '';
                if (!fixes || fixes.length === 0) {
                    dd.innerHTML = '<option value="">None</option>';
                } else {
                    dd.innerHTML = '<option value="">-- Select a fix --</option>';
                    fixes.forEach(function(f) {
                        var opt = document.createElement('option');
                        opt.value = f.id || f;
                        opt.textContent = f.name || f;
                        dd.appendChild(opt);
                    });
                }
            })
            .catch(function() {
                document.getElementById('peron-fixes-dd').innerHTML = '<option value="">None</option>';
            });

        // ── Fixes Apply ──
        document.getElementById('peron-fixes-apply').addEventListener('click', function(e) {
            e.preventDefault();
            var dd = document.getElementById('peron-fixes-dd');
            var st = document.getElementById('peron-fixes-status');
            var val = dd.value;
            if (!val) { st.textContent = 'Please select a fix first.'; st.style.color = '#e84040'; return; }
            st.textContent = 'Applying ' + val + '...';
            st.style.color = '#f8a524';
            fetch('http://127.0.0.1:3000/fixes/' + appId + '/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fix: val })
            }).then(function(r) {
                if (r.ok) { st.textContent = val + ' applied successfully.'; st.style.color = '#5ba32b'; }
                else { st.textContent = 'Error applying fix.'; st.style.color = '#e84040'; }
            }).catch(function() {
                st.textContent = 'Connection error.'; st.style.color = '#e84040';
            });
        });

        // ── Denuvo Get ──
        document.getElementById('peron-denuvo-get').addEventListener('click', function(e) {
            e.preventDefault();
            var st = document.getElementById('peron-denuvo-status');
            var input = document.getElementById('peron-denuvo-input');
            st.textContent = 'Extracting tickets...';
            st.style.color = '#f8a524';
            fetch('http://127.0.0.1:3000/denuvo/' + appId)
                .then(function(r) { return r.text(); })
                .then(function(data) {
                    input.value = data;
                    st.textContent = 'Done.';
                    st.style.color = '#5ba32b';
                })
                .catch(function() {
                    st.textContent = 'Error fetching token.';
                    st.style.color = '#e84040';
                });
        });

        // ── Denuvo Copy ──
        document.getElementById('peron-denuvo-copy').addEventListener('click', function(e) {
            e.preventDefault();
            var input = document.getElementById('peron-denuvo-input');
            var token = input.value.trim();
            if (!token) return;
            input.select();
            document.execCommand('copy');
            var st = document.getElementById('peron-denuvo-status');
            st.textContent = 'Copied to clipboard.';
            st.style.color = '#5ba32b';
        });

        // ── Denuvo Apply ──
        document.getElementById('peron-denuvo-apply').addEventListener('click', function(e) {
            e.preventDefault();
            var st = document.getElementById('peron-denuvo-status');
            var input = document.getElementById('peron-denuvo-input');
            var token = input.value.trim();
            if (!token) { st.textContent = 'Please paste a Denuvo token first.'; st.style.color = '#e84040'; return; }
            st.textContent = 'Applying Denuvo configuration...';
            st.style.color = '#f8a524';
            fetch('http://127.0.0.1:3000/denuvo/' + appId, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: token })
            }).then(function(r) {
                if (r.ok) { st.textContent = 'Denuvo configuration applied.'; st.style.color = '#5ba32b'; }
                else { st.textContent = 'Error applying Denuvo.'; st.style.color = '#e84040'; }
            }).catch(function() {
                st.textContent = 'Connection error.'; st.style.color = '#e84040';
            });
        });

        console.log('[Peron] Injected for app ' + appId);
    });
})();
"""

def inject_into_arena():
    tabs = requests.get("http://127.0.0.1:8080/json", timeout=5).json()
    target = next((t for t in tabs if t.get("title") == "Arena Breakout: Infinite"), None)
    if not target:
        print("Tab not found")
        return False

    ws = create_connection(target["webSocketDebuggerUrl"], timeout=10)
    ws.settimeout(5)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": PERON_JS}}))
    while True:
        raw = ws.recv()
        data = json.loads(raw)
        if data.get("id") == 1:
            err = data.get("result", {}).get("exceptionDetails")
            if err:
                print(f"Error: {err.get('text', err)}")
            else:
                print("Injected OK into Arena Breakout: Infinite")
            break
    ws.close()
    return True

if __name__ == "__main__":
    inject_into_arena()
