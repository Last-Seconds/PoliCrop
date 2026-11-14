/* Field Shift - placeholder rotation engine (DEMO).
 * All crop values below are illustrative placeholders (0-100, higher = better).
 * They will be replaced by values derived from NASA POWER / SMAP / SRTM / SSURGO etc.
 * Keep the same function signatures so the UI does not change.
 */
(function (root) {
  const CRITERIA = ['water', 'income', 'soil', 'erosion', 'risk', 'food'];

  const CROPS = {
    winter_wheat: { tr: 'Kışlık buğday', en: 'Winter wheat', water: 60, income: 70, soil: 45, erosion: 80, risk: 70, food: 85, legume: false },
    spring_wheat: { tr: 'Yazlık buğday', en: 'Spring wheat', water: 55, income: 62, soil: 42, erosion: 45, risk: 62, food: 75, legume: false },
    spring_barley: { tr: 'Yazlık arpa', en: 'Spring barley', water: 62, income: 55, soil: 45, erosion: 48, risk: 66, food: 70, legume: false },
    dry_pea: { tr: 'Kuru bezelye', en: 'Dry pea', water: 65, income: 58, soil: 82, erosion: 40, risk: 52, food: 55, legume: true },
    lentil: { tr: 'Mercimek', en: 'Lentil', water: 70, income: 66, soil: 85, erosion: 38, risk: 55, food: 50, legume: true },
    chickpea: { tr: 'Nohut', en: 'Chickpea', water: 78, income: 64, soil: 80, erosion: 40, risk: 45, food: 52, legume: true },
    canola: { tr: 'Kanola', en: 'Canola', water: 50, income: 68, soil: 55, erosion: 60, risk: 50, food: 40, legume: false }
  };

  const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
  const clamp = (x) => Math.max(0, Math.min(100, x));

  // sliders: {water, income, soil, erosion, risk} each 0..10
  function weightsFrom(sliders, drought) {
    const w = {
      water: sliders.water, income: sliders.income, soil: sliders.soil,
      erosion: sliders.erosion, risk: sliders.risk, food: 0
    };
    if (drought) {
      // "min water, max food" mode
      w.water = w.water * 2 + 4;
      w.food = 6;
      w.risk = w.risk * 1.5 + 1;
      w.income *= 0.5; w.soil *= 0.5; w.erosion *= 0.5;
    }
    return w;
  }

  function scoreRotation(seq, w, crops) {
    const avg = {};
    CRITERIA.forEach((k) => { avg[k] = mean(seq.map((c) => crops[c][k])); });
    const n = seq.length;
    const kinds = new Set(seq).size;
    let repeats = 0;
    for (let i = 0; i < n; i++) if (seq[i] === seq[(i + 1) % n]) repeats++;
    const legumeCount = seq.filter((c) => crops[c].legume).length;
    const hasLegume = legumeCount > 0;
    if (hasLegume) avg.soil = clamp(avg.soil + 6);
    // too many legumes in one short cycle can build up disease (placeholder rule)
    avg.risk = clamp(avg.risk + (kinds - 1) * 3 - repeats * 12 - Math.max(0, legumeCount - 1) * 8);
    avg.soil = clamp(avg.soil - repeats * 6);
    let wsum = 0, total = 0;
    CRITERIA.forEach((k) => { wsum += w[k]; total += w[k] * avg[k]; });
    const score = wsum > 0 ? total / wsum : mean(CRITERIA.map((k) => avg[k]));
    const riskIndex = clamp(100 - avg.risk);
    const spread = 6 + riskIndex / 6; // placeholder uncertainty band
    return { seq, avg, score, riskIndex, low: clamp(score - spread), high: clamp(score + spread), repeats, kinds, hasLegume };
  }

  function canon(seq) {
    const n = seq.length; let best = null;
    for (let i = 0; i < n; i++) {
      const r = seq.slice(i).concat(seq.slice(0, i)).join('|');
      if (best === null || r < best) best = r;
    }
    return best;
  }

  function rank(allowed, w, crops, len) {
    const L = len || 3; const seen = new Set(); const out = [];
    function rec(prefix) {
      if (prefix.length === L) {
        const key = canon(prefix);
        if (!seen.has(key)) { seen.add(key); out.push(scoreRotation(prefix.slice(), w, crops)); }
        return;
      }
      allowed.forEach((c) => { prefix.push(c); rec(prefix); prefix.pop(); });
    }
    rec([]);
    out.sort((a, b) => b.score - a.score);
    return out;
  }

  // state: {sliders, drought, excluded:Set, current:[ids], crops}
  function suggest(state) {
    const crops = state.crops;
    const allowed = Object.keys(crops).filter((c) => !state.excluded.has(c));
    const w1 = weightsFrom(state.sliders, state.drought);
    const current = scoreRotation(state.current, w1, crops);
    const curKey = canon(state.current);
    if (allowed.length < 2) return { w1, current, s1: null, s2: null, currentBest: false, label2: 'resilience' };
    const list1 = rank(allowed, w1, crops);
    const currentBest = list1[0].score <= current.score + 0.001;
    const s1 = list1.find((r) => canon(r.seq) !== curKey) || null;
    // second suggestion: a different objective (resilience, or soil health in drought mode)
    const w2 = state.drought
      ? { water: 1.5, income: 1, soil: 3, erosion: 3, risk: 1.5, food: 1 }
      : { water: 3, income: 1, soil: 1, erosion: 1.5, risk: 3, food: 1 };
    const list2 = rank(allowed, w2, crops);
    const setKey = (seq) => Array.from(new Set(seq)).sort().join('|');
    const curSet = setKey(state.current), set1 = s1 ? setKey(s1.seq) : null;
    // the second suggestion must use a different crop set, not just a different order
    const pick = list2.find((r) => { const k = setKey(r.seq); return k !== curSet && k !== set1; });
    const s2 = pick ? scoreRotation(pick.seq, w1, crops) : null; // shown on the user's weights
    return { w1, w2, current, s1, s2, currentBest, label2: state.drought ? 'soil' : 'resilience' };
  }

  const api = { CRITERIA, CROPS, weightsFrom, scoreRotation, rank, suggest, canon };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Engine = api;
})(typeof window !== 'undefined' ? window : globalThis);
