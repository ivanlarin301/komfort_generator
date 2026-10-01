/* Builds the card from the JSON in #card-data, fits text by font-size only, places the product and
   publishes window.__metrics / window.__ready for the renderer and QA (FR-6, FR-7, FR-9). */
(function () {
  "use strict";

  const W = 1080, H = 1350;
  const TEXT_LEFT = 78, TEXT_WIDTH = 924;
  const PRODUCT_GAP_TOP = 60;          // air between the subtitle block and the product (owner, 2026-10-01)
  const PRODUCT_BOTTOM = 1040;         // may slip a little under the translucent plate, never under code/price
  const PRODUCT_X = [90, 990];
  const CODE_RIGHT = 998, PRICE_RIGHT = 933, FOOTER_MIN_LEFT = 450;

  const SAMPLE = {
    title: "Кружка Luminarc", title_accent: null, subtitle: "", badge: ["«Марли» Эклипс, 250 мл"],
    plate: { value: "250 мл", label: "объём", style: "green", plus: true },
    code: "888735", price: "799", background: null, product: null, logo: "../../assets/logo.png", layout: {},
  };

  const dataEl = document.getElementById("card-data");
  const data = Object.assign({}, SAMPLE, dataEl ? JSON.parse(dataEl.textContent) : {});
  const card = document.getElementById("card");
  const M = { fonts: {}, overflow: {}, boxes: {}, loaded: {}, warnings: [], product: null };

  function el(tag, cls, parent) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    (parent || card).appendChild(node);
    return node;
  }

  function loadImage(img, src, key) {
    return new Promise((resolve) => {
      if (!src) { M.loaded[key] = false; resolve(); return; }
      img.onload = () => { M.loaded[key] = true; resolve(); };
      img.onerror = () => { M.loaded[key] = false; M.warnings.push(key + ": не удалось загрузить " + src); resolve(); };
      img.src = src;
    });
  }

  // Shrink font-size from maxPx to minPx until `measure()` <= limit. Returns the chosen size.
  function fit(node, maxPx, minPx, measure, limit, key) {
    let size = maxPx;
    node.style.fontSize = size + "px";
    while (measure() > limit && size > minPx) {
      size -= 1;
      node.style.fontSize = size + "px";
    }
    M.fonts[key] = size;
    M.overflow[key] = measure() > limit + 0.5;
    return size;
  }

  function box(node) {
    if (!node) return null;
    const r = node.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
             right: Math.round(r.right), bottom: Math.round(r.bottom) };
  }

  function appendWithAccent(node, text, accent) {
    if (accent) {
      const i = text.toLocaleLowerCase("ru").indexOf(accent.toLocaleLowerCase("ru"));
      if (i >= 0) {
        node.appendChild(document.createTextNode(text.slice(0, i)));
        const span = document.createElement("span");
        span.className = "accent";
        span.textContent = text.slice(i, i + accent.length);
        node.appendChild(span);
        node.appendChild(document.createTextNode(text.slice(i + accent.length)));
        return;
      }
      M.warnings.push("акцент «" + accent + "» не найден в заголовке");
    }
    node.textContent = text;
  }

  // "грузоподъемность **250 кг**" -> regular text with bold segments.
  function appendRich(node, text) {
    text.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
      if (!part) return;
      if (part.startsWith("**") && part.endsWith("**")) {
        const b = document.createElement("b");
        b.textContent = part.slice(2, -2);
        node.appendChild(b);
      } else {
        node.appendChild(document.createTextNode(part));
      }
    });
  }

  // ---------------------------------------------------------------- build
  const bg = el("img", "bg");
  bg.alt = "";
  const shadow = el("div", "product-shadow");
  const product = el("img", "product");
  product.alt = "";
  el("div", "shade-top");
  el("div", "shade-bottom");

  const title = el("h1", "title");
  appendWithAccent(title, data.title || "", data.title_accent);

  let subtitleLine = null;
  if (data.subtitle) {
    subtitleLine = el("p", "subtitle-line");
    subtitleLine.textContent = data.subtitle;
  }

  let badge = null;
  const badgeLines = (data.badge || []).filter((s) => s && String(s).trim());
  if (badgeLines.length) {
    badge = el("div", "badge");
    badgeLines.slice(0, 2).forEach((line, i) => {
      const span = el("span", i === 0 ? "l1" : "l2", badge);
      if (String(line).includes("**")) {
        span.style.fontWeight = "400";
        appendRich(span, String(line));
      } else {
        span.textContent = String(line);
      }
    });
  }

  let plate = null, plus = null;
  if (data.plate && data.plate.value) {
    const style = data.plate.style === "white" ? "white" : "green";
    plate = el("div", "plate " + style + (data.plate.label ? "" : " single"));
    el("div", "v", plate).textContent = data.plate.value;
    if (data.plate.label) el("div", "l", plate).textContent = data.plate.label;
    if (data.plate.plus !== false) {
      plus = el("div", "plus " + (style === "white" ? "on-white" : "on-green"));
      plus.textContent = "+";
    }
  }
  if ((data.features || []).length) M.warnings.push("иконки-свойства пока не поддерживаются шаблоном (TSK-016)");

  let logo = null;
  if (data.logo) {
    logo = el("img", "logo");
    logo.alt = "Комфорт";
  } else {
    M.warnings.push("логотип не найден: assets/logo.png");
  }

  const code = el("p", "code");
  code.textContent = "КОД: " + (data.code || "");
  const price = el("p", "price");
  price.textContent = data.price || "";
  const tenge = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  tenge.setAttribute("class", "tenge");
  tenge.setAttribute("viewBox", "0 0 47 75");
  tenge.innerHTML = '<rect x="0" y="0" width="47" height="13" fill="#fff"/>' +
    '<rect x="0" y="22" width="47" height="13" fill="#fff"/><rect x="17" y="22" width="13" height="53" fill="#fff"/>';
  card.appendChild(tenge);

  // ---------------------------------------------------------------- layout
  function layoutText() {
    // Title: one line 93 -> 58px; if it still does not fit, two lines 70 -> 50px.
    fit(title, 93, 58, () => title.scrollWidth, TEXT_WIDTH, "title");
    if (M.overflow.title) {
      title.classList.add("two-lines");
      // Count lines from the layout height: scrollHeight would include Open Sans' tall ascender overflow.
      const lines = () => Math.round(title.offsetHeight / parseFloat(getComputedStyle(title).lineHeight));
      fit(title, 70, 50, () => (title.scrollWidth > TEXT_WIDTH ? 1e9 : lines()), 2, "title");
      M.fonts.title_lines = 2;
    } else {
      M.fonts.title_lines = 1;
    }
    let y = title.offsetTop + title.offsetHeight;

    if (subtitleLine) {
      subtitleLine.style.top = (y + 2) + "px";
      fit(subtitleLine, 48, 34, () => subtitleLine.scrollWidth, TEXT_WIDTH, "subtitle");
      y = subtitleLine.offsetTop + subtitleLine.offsetHeight;
    }
    if (badge) {
      badge.style.top = (y + 18) + "px";
      const spans = Array.from(badge.querySelectorAll("span"));
      const widest = () => Math.max.apply(null, spans.map((s) => s.scrollWidth)) + 60;
      let size = 34;
      const apply = () => spans.forEach((s, i) => { s.style.fontSize = (i === 0 ? size : Math.round(size * 0.88)) + "px"; });
      apply();
      while (widest() > TEXT_WIDTH && size > 24) { size -= 1; apply(); }
      M.fonts.badge = size;
      M.overflow.badge = widest() > TEXT_WIDTH + 0.5;
      y = badge.offsetTop + badge.offsetHeight;
    }
    M.text_bottom = y;

    if (plate) {
      const v = plate.querySelector(".v");
      fit(v, plate.classList.contains("single") ? 40 : 48, 28, () => v.scrollWidth, 341 - 36, "plate");
    }
    fit(code, 45, 34, () => code.scrollWidth, CODE_RIGHT - FOOTER_MIN_LEFT, "code");
    fit(price, 110, 80, () => price.scrollWidth, PRICE_RIGHT - FOOTER_MIN_LEFT, "price");
  }

  function layoutProduct() {
    if (!M.loaded.product || !product.naturalWidth) {
      product.style.display = "none";
      shadow.style.display = "none";
      return;
    }
    const lay = data.layout || {};
    const zone = lay.product_zone || [PRODUCT_X[0], M.text_bottom + PRODUCT_GAP_TOP, PRODUCT_X[1], PRODUCT_BOTTOM];
    const [x0, y0, x1, y1] = zone;
    const zw = x1 - x0, zh = y1 - y0;
    const scale = Math.min(zw / product.naturalWidth, zh / product.naturalHeight) * Math.min(1, Math.max(0.5, lay.scale || 1));
    const dw = product.naturalWidth * scale, dh = product.naturalHeight * scale;
    const left = x0 + (zw - dw) / 2 + (lay.offset_x || 0);
    const top = y1 - dh + (lay.offset_y || 0);
    Object.assign(product.style, { left: left + "px", top: top + "px", width: dw + "px", height: dh + "px" });
    const sw = dw * 0.8, sh = Math.max(20, Math.min(70, dw * 0.08));
    Object.assign(shadow.style, { left: (left + (dw - sw) / 2) + "px", top: (top + dh - sh * 0.55) + "px",
      width: sw + "px", height: sh + "px" });
    M.product = { zone: zone, x: Math.round(left), y: Math.round(top), w: Math.round(dw), h: Math.round(dh),
      area_ratio: +((dw * dh) / (W * H)).toFixed(3) };
  }

  function collectBoxes() {
    const nodes = { title, subtitle: subtitleLine, badge, plate, plus, logo, code, price, tenge };
    Object.keys(nodes).forEach((k) => { if (nodes[k]) M.boxes[k] = box(nodes[k]); });
    if (M.product) M.boxes.product = { x: M.product.x, y: M.product.y, w: M.product.w, h: M.product.h,
      right: M.product.x + M.product.w, bottom: M.product.y + M.product.h };
  }

  Promise.all([
    document.fonts.ready,
    loadImage(bg, data.background, "background"),
    loadImage(product, data.product, "product"),
    logo ? loadImage(logo, data.logo, "logo") : Promise.resolve(),
  ]).then(() => {
    if (!M.loaded.background) bg.style.display = "none";
    layoutText();
    layoutProduct();
    collectBoxes();
    M.fonts_loaded = ["Open Sans", "Montserrat"].every((f) => document.fonts.check("700 40px \"" + f + "\""));
    window.__metrics = M;
    window.__ready = true;
  });
})();
