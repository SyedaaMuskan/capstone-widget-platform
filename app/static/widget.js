/* Embeddable widget bundle. Loaded (versioned URL) by /widget.js?id=<widget id>.
   Reads config from the API, renders a form, submits cross-origin. Minimal on purpose. */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var id = script.getAttribute('data-widget-id');
  var api = script.getAttribute('data-api');
  if (!id || !api) return;

  function el(tag, props, text) {
    var n = document.createElement(tag);
    for (var k in (props || {})) n.setAttribute(k, props[k]);
    if (text) n.textContent = text;   // textContent, never innerHTML: config is data, not markup
    return n;
  }
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'k' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  function render(cfg) {
    var o = cfg.options || {};
    var color = o.theme_color || '#2563eb';
    var box = el('div', { 'data-flyrank-widget': cfg.id });
    var pos = o.position || 'inline';
    var css = 'font-family:system-ui,sans-serif;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;max-width:360px;box-shadow:0 4px 16px rgba(0,0,0,.08);';
    if (pos === 'bottom-right') css += 'position:fixed;right:20px;bottom:20px;z-index:2147483000;';
    if (pos === 'bottom-left') css += 'position:fixed;left:20px;bottom:20px;z-index:2147483000;';
    if (pos === 'center') css += 'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2147483000;';
    box.setAttribute('style', css);

    box.appendChild(el('h3', { style: 'margin:0 0 6px;font-size:18px' }, cfg.title));
    if (cfg.description) box.appendChild(el('p', { style: 'margin:0 0 12px;color:#4b5563;font-size:14px' }, cfg.description));

    var form = el('form', { novalidate: 'novalidate' });
    var inputs = {};
    cfg.fields.forEach(function (f) {
      var wrap = el('label', { style: 'display:block;margin-bottom:10px;font-size:13px;color:#374151' }, f.label + (f.required ? ' *' : ''));
      var input = f.type === 'textarea' ? el('textarea', { rows: '3' }) : el('input', { type: f.type === 'text' ? 'text' : f.type });
      input.setAttribute('name', f.name);
      input.setAttribute('maxlength', String(f.max_length));
      input.setAttribute('style', 'display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:8px;border:1px solid #d1d5db;border-radius:6px;font:inherit');
      inputs[f.name] = input;
      wrap.appendChild(input);
      form.appendChild(wrap);
    });

    // Honeypot: invisible to humans, tempting to bots.
    var hp = el('input', { type: 'text', name: 'hp', tabindex: '-1', autocomplete: 'off', 'aria-hidden': 'true',
                           style: 'position:absolute;left:-9999px;width:1px;height:1px;opacity:0' });
    form.appendChild(hp);

    var msg = el('div', { style: 'min-height:18px;margin:6px 0;font-size:13px', role: 'status' });
    var btn = el('button', { type: 'submit', style: 'background:' + color + ';color:#fff;border:0;border-radius:6px;padding:9px 14px;font:inherit;cursor:pointer' }, cfg.button_text);
    form.appendChild(msg);
    form.appendChild(btn);
    box.appendChild(form);

    var key = uuid(); // same key on retries => the server stores the submission once
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var data = {};
      Object.keys(inputs).forEach(function (n) { data[n] = inputs[n].value; });
      btn.disabled = true; msg.style.color = '#374151'; msg.textContent = 'Sending...';
      fetch(api + '/submissions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
        body: JSON.stringify({ widget_id: cfg.id, data: data, hp: hp.value })
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, body: j }; });
      }).then(function (res) {
        if (res.status >= 200 && res.status < 300) {
          msg.style.color = '#15803d'; msg.textContent = o.success_message || 'Thanks!';
          form.reset(); key = uuid();
        } else if (res.status === 422 && res.body.error && res.body.error.details) {
          msg.style.color = '#b91c1c';
          msg.textContent = res.body.error.details.map(function (d) { return d.field + ': ' + d.message; }).join(' | ');
        } else if (res.status === 429) {
          msg.style.color = '#b91c1c'; msg.textContent = 'Too many attempts. Please wait a moment.';
        } else {
          msg.style.color = '#b91c1c'; msg.textContent = (res.body.error && res.body.error.message) || 'Something went wrong.';
        }
      }).catch(function () {
        msg.style.color = '#b91c1c'; msg.textContent = 'Network error. Please try again.';
      }).then(function () { btn.disabled = false; });
    });

    var mount = function () {
      var target = (pos === 'inline') ? document.getElementById('flyrank-widget') : null;
      (target || document.body).appendChild(box);
    };
    var delay = (o.delay_seconds || 0) * 1000;
    if (delay > 0) setTimeout(mount, delay); else mount();
  }

  function start() {
    fetch(api + '/widgets/' + encodeURIComponent(id) + '/config')
      .then(function (r) { if (!r.ok) throw new Error('config ' + r.status); return r.json(); })
      .then(render)
      .catch(function (e) { if (window.console) console.warn('[widget] could not load', e); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
