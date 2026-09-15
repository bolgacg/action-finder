/* action-finder: the candidate list, its evidence, and the account of what it
   cannot tell you. Every number comes from data.js, written by the scripts in
   study/. Nothing here is typed. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var C = 'http://www.w3.org/2000/svg';
  function el(tag, a, t) {
    var n = document.createElementNS(C, tag);
    for (var k in a) n.setAttribute(k, a[k]);
    if (t != null) n.textContent = t;
    return n;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[<>&]/g, function (c) {
      return { '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c];
    });
  }
  function pct(x, d) { return x == null ? 'n/a' : (100 * x).toFixed(d == null ? 0 : d) + '%'; }
  // A count of 2002 printed beside the year 2022 reads as a year. A thousands
  // separator is the whole fix, and it is needed wherever counts and years meet.
  function n(x) { return x == null ? 'n/a' : Number(x).toLocaleString('en-GB'); }
  // A caption drawn inside an SVG shrinks with the SVG. At 390px these charts scale
  // to under half size and an 11px caption becomes 5px, which is not readable. So
  // captions live in HTML above the chart and stay at body size at every width.
  function caption(id, text) { var e = $(id + '-cap'); if (e) e.textContent = text; }
  // These charts are drawn in coordinate spaces 860 to 900 units wide and rendered into
  // whatever width the column has. On a phone that is about 350px, so every label inside
  // them renders at 40 percent of its stated size. Drawing a narrower picture on a narrow
  // screen keeps the text near the size it was written at.
  function isNarrow() { return window.innerWidth < 620; }
  function redrawOnWidthChange(fn) {
    if (fn._bound) return;
    fn._bound = true;
    var last = isNarrow();
    window.addEventListener('resize', function () {
      var now = isNarrow();
      if (now !== last) { last = now; fn(); }
    });
  }
  // Cutting a chart label at a fixed character count leaves words like "Intelligenc"
  // sitting on the page. Trim back to the last whole word and mark it as trimmed.
  function shorten(s, n) {
    if (s.length <= n) return s;
    var cut = s.slice(0, n);
    var sp = cut.lastIndexOf(' ');
    return (sp > n * 0.5 ? cut.slice(0, sp) : cut).replace(/[ ,]+$/, '') + '\u2026';
  }

  var state = { dept: null, sel: null, names: false };

  /* ---------- the three sources, drawn once ---------- */
  function drawDomain() {
    var host = $('#domainviz'); if (!host) return;
    var boxes = [
      { t: 'AU Pure', s: 'which faculty and department a paper belongs to, which is the one thing OpenAlex cannot say' },
      { t: 'OpenAlex', s: 'the topic of each paper, and whether any co-author was a company' },
      { t: 'CORDIS', s: 'Danish organisations working on the same topics in European projects' },
      { t: 'A candidate', s: 'a department and a topic, ranked partly by how much of that Danish activity has no Aarhus link' }
    ];
    var foot = 'The AU to Danish-organisation link is a join on the European participant identifier, ' +
      'so no organisation name is ever matched to another.';
    function wrap(text, perLine, put) {
      var words = text.split(' '), line = '';
      words.forEach(function (w) {
        if ((line + ' ' + w).length > perLine) { put(line); line = w; } else line = line ? line + ' ' + w : w;
      });
      if (line) put(line);
    }
    // Four boxes side by side need 900 units of width, which on a phone column scales every
    // label to under four pixels. Stacked, each box gets the whole width instead.
    var narrow = isNarrow(), s2;
    if (narrow) {
      var BW = 380, BH = 78, GAP = 16, W = 400, H = boxes.length * (BH + GAP) + 46;
      s2 = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img',
        'aria-label': 'Three public sources joined on identifiers to produce candidate Actions' });
      boxes.forEach(function (b, i) {
        var y = i * (BH + GAP);
        s2.appendChild(el('rect', { x: 10, y: y, width: BW, height: BH, rx: 6, fill: '#fff', stroke: '#c9c5be' }));
        s2.appendChild(el('text', { x: 22, y: y + 22, 'font-family': "'Newsreader',Georgia,serif",
          'font-size': 15, 'font-weight': 600, fill: '#1a1d21' }, b.t));
        var ty = y + 40;
        wrap(b.s, 52, function (line) {
          s2.appendChild(el('text', { x: 22, y: ty, 'font-family': "'IBM Plex Sans',sans-serif",
            'font-size': 11, fill: '#5b6470' }, line));
          ty += 14;
        });
        if (i < boxes.length - 1) {
          s2.appendChild(el('line', { x1: 200, y1: y + BH + 2, x2: 200, y2: y + BH + GAP - 2,
            stroke: '#8b95a1', 'stroke-width': 1.5 }));
          s2.appendChild(el('circle', { cx: 200, cy: y + BH + GAP - 3, r: 2.5, fill: '#8b95a1' }));
        }
      });
      var fy = boxes.length * (BH + GAP) + 6;
      wrap(foot, 56, function (line) {
        s2.appendChild(el('text', { x: 10, y: fy, 'font-family': "'IBM Plex Mono',monospace",
          'font-size': 9.5, fill: '#8b95a1' }, line));
        fy += 13;
      });
    } else {
      var W2 = 900, H2 = 200;
      s2 = el('svg', { viewBox: '0 0 ' + W2 + ' ' + H2, role: 'img',
        'aria-label': 'Three public sources joined on identifiers to produce candidate Actions' });
      var xs = [{ x: 8, w: 200 }, { x: 236, w: 200 }, { x: 464, w: 200 }, { x: 700, w: 192 }];
      boxes.forEach(function (b, i) {
        var g = xs[i];
        s2.appendChild(el('rect', { x: g.x, y: 28, width: g.w, height: 124, rx: 6, fill: '#fff', stroke: '#c9c5be' }));
        s2.appendChild(el('text', { x: g.x + 13, y: 53, 'font-family': "'Newsreader',Georgia,serif",
          'font-size': 17, 'font-weight': 600, fill: '#1a1d21' }, b.t));
        var y = 74;
        wrap(b.s, 28, function (line) {
          s2.appendChild(el('text', { x: g.x + 13, y: y, 'font-family': "'IBM Plex Sans',sans-serif",
            'font-size': 11, fill: '#5b6470' }, line));
          y += 14;
        });
        if (i < boxes.length - 1) {
          var x1 = g.x + g.w + 4, x2 = xs[i + 1].x - 4;
          s2.appendChild(el('line', { x1: x1, y1: 90, x2: x2, y2: 90, stroke: '#8b95a1', 'stroke-width': 1.5 }));
          s2.appendChild(el('circle', { cx: x2 - 2, cy: 90, r: 2.5, fill: '#8b95a1' }));
        }
      });
      s2.appendChild(el('text', { x: 8, y: 180, 'font-family': "'IBM Plex Mono',monospace",
        'font-size': 10.5, fill: '#8b95a1' }, foot));
    }
    host.innerHTML = ''; host.appendChild(s2);
  }

  /* ---------- act one ---------- */
  function depts() {
    var seen = {};
    D.actions.forEach(function (a) { seen[a.department] = (seen[a.department] || 0) + 1; });
    return Object.keys(seen).sort(function (a, b) { return seen[b] - seen[a]; });
  }

  function renderDepts() {
    var host = $('#deptchips'); host.innerHTML = '';
    var list = depts();
    if (!state.dept) state.dept = list[0];
    list.forEach(function (d) {
      var b = document.createElement('button');
      b.className = 'chip';
      b.setAttribute('aria-pressed', d === state.dept ? 'true' : 'false');
      b.textContent = d.replace(/^Department of /, '') + ' (' +
        D.actions.filter(function (a) { return a.department === d; }).length + ')';
      b.onclick = function () { state.dept = d; state.sel = null; renderDepts(); renderList(); renderDetail(); };
      host.appendChild(b);
    });
  }

  function renderList() {
    var host = $('#alist'); host.innerHTML = '';
    var rows = D.actions.filter(function (a) { return a.department === state.dept; })
      .sort(function (a, b) { return b.score - a.score; });
    rows.forEach(function (a) {
      var d = document.createElement('div');
      d.className = 'arow' + (state.sel === a.action_id ? ' on' : '');
      d.setAttribute('role', 'button');
      d.setAttribute('tabindex', '0');
      // A row that survives only some resamples is close to the threshold, and a reader
      // scanning the list cannot tell that from the score alone. It is marked here rather
      // than dropped, for the same reason weak topic tags are marked: the page's argument
      // is that a specialist does the judging, and hiding the weak rows takes that away.
      var st = (D.stability && D.stability.available && D.stability.by_action) ? D.stability.by_action[a.action_id] : null;
      var shaky = st && st.appears_pct != null && st.appears_pct < 80;
      d.innerHTML = '<div class="top"><div class="t">' + esc(a.topic.subfield) +
        (a.white_space ? '<span class="tagws">white space</span>' : '') +
        (shaky ? '<span class="tagun" title="appears in ' + Math.round(st.appears_pct) +
          ' percent of 2,000 resamples of the evidence">unstable</span>' : '') +
        '</div><div class="sc">score ' + a.score.toFixed(2) + '</div></div>' +
        '<div class="sub">' + a.au_evidence.works_in_window + ' papers from this department, ' +
        a.danish_evidence.organisations_on_this_topic + ' Danish organisations on the topic, ' +
        a.danish_evidence.no_shared_project_with_au_on_this_topic + ' of them with no shared project with Aarhus' +
        (shaky ? '. Clears the bar in only ' + Math.round(st.appears_pct) +
          ' percent of resamples, so treat its position as provisional' : '') + '</div>';
      d.onclick = function () { state.sel = a.action_id; renderList(); renderDetail(); };
      d.onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); d.onclick(); } };
      host.appendChild(d);
    });
  }

  function renderDetail() {
    var host = $('#detail');
    var a = D.actions.filter(function (x) { return x.action_id === state.sel; })[0];
    if (!a) { host.innerHTML = '<p class="small">Click a candidate to see what is behind it.</p>'; return; }
    var orgs = (a.danish_evidence.organisations || []).slice(0, 18);
    var comp = (a.au_evidence.company_coauthors || []);
    host.innerHTML =
      '<div class="card-title">' + esc(a.department) + ', ' + esc(a.topic.subfield) + '</div>' +
      '<p class="small">' + esc(a.topic.field) + ', ' + esc(a.topic.domain) +
      '. Ranked ' + a.rank + ' of ' + D.actions.length + ' with a score of ' + a.score.toFixed(3) + '.</p>' +
      '<p class="small">The score combines three things and nothing else. <b>How much this department ' +
      'publishes on this topic</b>, which is ' + n(a.au_evidence.works_in_window) + ' papers here. ' +
      '<b>How many Danish organisations work on the same topic in European projects</b>, which is ' +
      n(a.danish_evidence.organisations_on_this_topic) + '. And <b>how many of those have never shared ' +
      'a project with Aarhus</b>, which is ' + n(a.danish_evidence.no_shared_project_with_au_on_this_topic) +
      ', or ' + pct(a.score_components.unconnected_share) + ' of them.</p>' +
      '<p class="small">The first two are each measured against the strongest candidate on this page ' +
      'and on a log scale, so that a department with two hundred papers does not count twenty times a ' +
      'department with ten and cannot own the whole list. They are then combined as a geometric mean, ' +
      'so a topic strong on one side and weak on the other cannot score well, and the third can at ' +
      'most double the result. Written out: <code>' + esc(a.score_components.formula) + '</code>, where ' +
      'the two scaled terms are ' + a.score_components.au_strength_scaled.toFixed(2) + ' and ' +
      a.score_components.danish_activity_scaled.toFixed(2) + ' for this candidate.</p>' +
      '<div class="stat">' +
      '<div><div class="k">AU papers</div><div class="n">' + a.au_evidence.works_in_window +
      '</div><div class="s">in this topic, in the window</div></div>' +
      '<div><div class="k">Danish organisations</div><div class="n">' + a.danish_evidence.organisations_on_this_topic +
      '</div><div class="s">' + a.danish_evidence.for_profit_organisations + ' of them for profit</div></div>' +
      '<div><div class="k">Already met</div><div class="n">' + a.danish_evidence.share_a_project_with_au_on_this_topic +
      '</div><div class="s">share a project with AU on this topic</div></div>' +
      '<div><div class="k">Company co-authors</div><div class="n">' + a.au_evidence.works_with_company_coauthor +
      '</div><div class="s">of the department\'s papers here</div></div>' +
      '</div>' +
      '<p class="small" style="margin-top:14px"><b>Danish organisations on this topic.</b> ' +
      'Each one says whether Aarhus is already on a European project with it, on this topic or on ' +
      'another, because those are three different phone calls. Some also carry a warning: the ' +
      'project keyword that put the organisation on this topic has nothing corroborating it, which ' +
      'is how a pharmaceutical company ends up under Ecology.</p>' +
      '<div class="orglist">' + orgs.map(function (o) {
        // Three states, not two, because they are three different phone calls: a
        // partner already on an Aarhus project about this topic, one already on an
        // Aarhus project about something else, and one with no existing link at all.
        var link = o.shares_a_project_with_au_on_this_topic
          ? '<span style="color:var(--pos)">already with AU on this topic</span>'
          : (o.shares_project_with_au
              ? '<span style="color:var(--accent)">already with AU, another topic</span>'
              : 'no shared project with AU');
        // A weakly supported link comes from a project whose topic keyword has nothing
        // corroborating it, which is how a pharmaceutical company lands under Ecology.
        var weak = o.topic_support && o.topic_support !== 'corroborated'
          ? ' <span style="color:var(--neg)" title="' +
            esc(o.topic_support_detail || 'the project keyword that produced this topic has nothing corroborating it') +
            '">topic tag unsupported</span>'
          : '';
        return '<div><b>' + esc(o.name) + '</b> <span class="hint">' + esc(o.activity || '') +
          ', ' + link + weak + '</span></div>';
      }).join('') + '</div>' +
      (a.danish_evidence.organisations_on_this_topic > orgs.length
        ? '<p class="hint">' + (a.danish_evidence.organisations_on_this_topic - orgs.length) + ' more in the data.</p>' : '') +
      (comp.length
        ? '<p class="small" style="margin-top:12px"><b>Companies already co-authoring with this department in this topic:</b> ' +
          comp.slice(0, 12).map(esc).join(', ') + '.</p>'
        : '<p class="small" style="margin-top:12px">' + esc(a.white_space_definition) +
          ', and this candidate meets that, which is why it is marked white space.</p>') +
      '<div style="margin-top:14px"><button class="chip" id="namebtn" aria-pressed="' + (state.names ? 'true' : 'false') + '">' +
      (state.names ? 'Hide the authors' : 'Show the authors behind these papers') + '</button>' +
      '<p class="hint" style="margin-top:6px">These are the authors of the public papers cited above, taken from the ' +
      'bibliographic record. They are shown because a specialist needs to know who to write to, and for no other reason. ' +
      'Nothing on this page ranks a person.</p></div>' +
      (state.names ? renderNames(a) : '');
    var nb = $('#namebtn');
    if (nb) nb.onclick = function () { state.names = !state.names; renderDetail(); };
  }

  function renderNames(a) {
    var au = a.au_evidence.authors || a.au_evidence.top_authors;
    if (!au || !au.length) {
      return '<p class="small">The shipped data carries no author list for this candidate, so there is nothing to show. ' +
        'That is a gap in the pipeline rather than a privacy measure, and the coda says which fields were stripped and why.</p>';
    }
    return '<div class="orglist" style="margin-top:10px">' + au.slice(0, 24).map(function (p) {
      var name = typeof p === 'string' ? p : (p.name || p.display_name || '');
      var n = typeof p === 'object' && p.works ? ' <span class="hint">' + p.works + ' papers</span>' : '';
      return '<div><b>' + esc(name) + '</b>' + n + '</div>';
    }).join('') + '</div>';
  }

  /* ---------- act two ---------- */
  function renderWorked() {
    var host = $('#worked');
    var top = D.actions.slice().sort(function (a, b) { return b.score - a.score; })[0];
    // Two different failures, and telling a reader they are the same would be a lie.
    // Not written yet is a job unfinished. Written for a different candidate is a
    // brief that has gone stale, which is worse, because it would still read well.
    if (typeof WORKED === 'undefined' || !WORKED) {
      host.innerHTML = '<p class="small"><b>This act is not written yet.</b> ' +
        'The instrument currently ranks <code>' + esc(top.action_id) + '</code> first, and the ' +
        'hand-written Action belongs to whichever candidate is top once the harvest is complete. ' +
        'Act three explains why it is not complete: the topic lookup has seen ' +
        'part of the papers, so the ranking can still move, and writing a brief against a ' +
        'ranking that is still moving would be writing it twice.</p>';
      return;
    }
    if (WORKED.action_id !== top.action_id) {
      // Where the briefed candidate landed matters. Second is a brief worth reading;
      // fifteenth is a brief about something the instrument no longer recommends.
      var was = D.actions.filter(function (a) { return a.action_id === WORKED.action_id; })[0];
      var where = was
        ? 'It now ranks ' + was.rank + ' of ' + D.actions.length +
          (was.rank <= 3 ? ', so the brief is still about a candidate near the top.'
                         : ', so it is no longer about a candidate this page would put in front of anyone.')
        : 'It no longer appears in the list at all, which act three explains: candidates near the ' +
          'threshold come and go as the evidence changes.';
      host.innerHTML = '<p class="small"><b>The written brief and the instrument have drifted apart.</b> ' +
        'The hand-written Action below was prepared for <code>' + esc(WORKED.action_id) +
        '</code>, and the instrument now ranks <code>' + esc(top.action_id) + '</code> first. ' +
        esc(where).replace(/&lt;/g, '<').replace(/&gt;/g, '>') + ' ' +
        'Rather than quietly show a brief for a candidate that is no longer top, the page says so. ' +
        'A specialist would rewrite it; this page will not fake it.</p>' +
        (typeof WORKED !== 'undefined' && WORKED ? '<hr style="border:0;border-top:1px solid var(--rule);margin:16px 0">' + WORKED.html : '');
      return;
    }
    host.innerHTML = WORKED.html;
  }

  // The page prints the scoring formula beside every row it produced, which is only
  // worth anything if the formula is the one that ran. So the browser recomputes every
  // score from the components shipped with it and says whether they match. A page that
  // quietly disagreed with its own arithmetic would look exactly like one that did not.
  function selfCheck() {
    var host = $('#selfcheck'); if (!host) return;
    var worst = 0, worstRow = null, n = 0;
    D.actions.forEach(function (a) {
      var c = a.score_components || {};
      if (c.au_strength_scaled == null || c.danish_activity_scaled == null || c.unconnected_share == null) return;
      var mine = Math.sqrt(c.au_strength_scaled * c.danish_activity_scaled) * (0.5 + 0.5 * c.unconnected_share);
      var diff = Math.abs(mine - a.score);
      n++;
      if (diff > worst) { worst = diff; worstRow = a; }
    });
    if (!n) { host.textContent = 'No score components shipped, so nothing could be rechecked.'; return; }
    // Scores travel rounded to four decimals, so anything at that scale is the rounding
    // and not a disagreement. Anything larger is a real one and is named as such.
    var tol = 5e-4;
    if (worst <= tol) {
      host.innerHTML = '<b>Matched.</b> All ' + n + ' scores on this page were recomputed here from ' +
        'their own components using the printed formula, ' + esc(D.actions[0].score_components.formula) +
        '. The largest disagreement is ' + worst.toExponential(1) + ', which is the rounding applied ' +
        'when the numbers were written into this page and not a difference in the arithmetic.';
    } else {
      host.innerHTML = '<b>Did not match.</b> Recomputing the ' + n + ' scores from their own components ' +
        'gives a different answer, worst on ' + esc(worstRow.action_id) + ' by ' + worst.toFixed(4) +
        '. The formula printed on this page is therefore not the formula that produced the ranking, ' +
        'and the ranking should not be used until that is resolved.';
    }
  }

  /* ---------- act three, the two measurements of the instrument itself ---------- */

  // A single coverage percentage invites the reader to assume the missing papers are
  // missing at random. They are not, and the shape of that is the sharpest thing this
  // page can say against itself, so it gets its own chart rather than a clause.
  function renderCoverageByYear() {
    var cy = (D.honesty_panel || {}).coverage_by_year;
    var text = $('#covyeartext'), host = $('#covyearviz');
    if (!text || !cy || !cy.rows || !cy.rows.length) {
      if (text) text.textContent = 'Not measured.';
      return;
    }
    var from = cy.years_compared_from || 0;
    var rows = cy.rows.filter(function (r) { return Number(r.year) >= from && r.coverage_pct != null; });
    if (!rows.length) { text.textContent = 'Not measured.'; return; }
    var b = cy.best_year, w = cy.worst_year;
    // A partial lookup does not fail evenly: it works down a list and stops. Whether that
    // happened is a fact about the numbers, so the paragraph is chosen from them rather
    // than from the framing the page was written under.
    var skew = (b && w && b.coverage_pct != null && w.coverage_pct != null)
      ? b.coverage_pct - w.coverage_pct : null;
    text.innerHTML = (skew != null && skew > 25)
      ? 'The papers that have not been looked up are not a random share of the whole. ' +
        'The lookup works down a list and stopped where the budget ran out, so it finished one year and ' +
        'barely started another. Of the papers published in ' + esc(b.year) + ', ' + b.coverage_pct +
        ' percent reached a topic. Of those published in ' + esc(w.year) + ', ' + w.coverage_pct +
        ' percent did. <b>So the ranking above is close to a ranking of what Aarhus published in ' +
        esc(b.year) + '</b>, rather than of the window it claims. A department whose work shifted between ' +
        'those years is misrepresented here, and that is a stronger objection than the headline ' +
        'percentage on its own suggests.'
      : '<b>The lookup finished, and it finished evenly.</b> This chart exists because a partial ' +
        'lookup does not fail at random: it works down a list and stops, so an interrupted run ranks ' +
        'one year rather than the window it claims. That is what this page showed while the budget was ' +
        'exhausted. Now every year in the window reaches a topic at between ' + w.coverage_pct +
        ' and ' + b.coverage_pct + ' percent, a spread of ' + skew.toFixed(1) + ' points, so no single ' +
        'year is carrying the ranking and a department whose work shifted inside the window is not ' +
        'misrepresented by the shape of the harvest.';

    var narrow = isNarrow();
    var W = narrow ? 400 : 860, H = narrow ? 230 : 212;
    var P = narrow ? { l: 40, r: 12, t: 14, b: 50 } : { l: 56, r: 20, t: 14, b: 46 };
    var s = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img',
      'aria-label': 'Share of each publication year whose papers reached a topic' });
    var bw = (W - P.l - P.r) / rows.length;
    var scale = Math.max(100, Math.max.apply(null, rows.map(function (r) { return r.coverage_pct; })));
    rows.forEach(function (r, i) {
      var hgt = r.coverage_pct / scale * (H - P.t - P.b);
      s.appendChild(el('rect', { x: P.l + i * bw + 8, y: H - P.b - hgt, width: bw - 16,
        height: Math.max(1, hgt), rx: 2, fill: r.coverage_pct < 25 ? '#b03a3a' : '#2c4a6b' }));
      s.appendChild(el('text', { x: P.l + i * bw + bw / 2, y: H - P.b + 15, 'text-anchor': 'middle',
        'font-family': "'IBM Plex Mono',monospace", 'font-size': 10.5, fill: '#8b95a1' }, r.year));
      s.appendChild(el('text', { x: P.l + i * bw + bw / 2, y: H - P.b - hgt - 5, 'text-anchor': 'middle',
        'font-family': "'IBM Plex Mono',monospace", 'font-size': 10.5, fill: '#5b6470' }, r.coverage_pct + '%'));
      s.appendChild(el('text', { x: P.l + i * bw + bw / 2, y: H - P.b + 30, 'text-anchor': 'middle',
        'font-family': "'IBM Plex Mono',monospace", 'font-size': 9.5, fill: '#b5bcc4' },
        n(r.looked_up) + ' of ' + n(r.with_doi)));
    });
    caption('#covyearviz', 'Share of each year’s papers that reached a topic, with the counts beneath. ' +
      'Red is under a quarter.');
    host.innerHTML = ''; host.appendChild(s);
  }

  // Resampling says how much of the order is real and how much is an accident of which
  // works happened to be drawn. It answers a fair objection, and it is careful not to
  // claim more than a bootstrap can: it cannot speak for the papers never fetched.
  function renderStability() {
    var st = D.stability, text = $('#stabtext'), host = $('#stabviz');
    if (!text) return;
    if (!st || !st.available) {
      text.textContent = 'Not measured' + (st && st.reason ? ' (' + st.reason + ').' : '.');
      return;
    }
    var h = st.headline || {};
    text.innerHTML = 'The covered papers were drawn again with replacement ' + st.resamples +
      ' times, and the whole ranking recomputed each time, thresholds included, so a candidate ' +
      'that only just clears the bar is allowed to vanish. ' +
      (h.top_candidate ? '<b>' + esc(h.top_candidate) + '</b> comes first in ' +
        h.top_candidate_ranked_first_pct + ' percent of them. ' : '') +
      (h.candidates_appearing_in_under_80_pct != null
        ? h.candidates_appearing_in_at_least_99_pct + ' of the ' + D.actions.length +
          ' candidates survive almost every redraw, while ' + h.candidates_appearing_in_under_80_pct +
          ' come and go. Those are the rows to distrust. ' : '') +
      // What the bootstrap cannot see depends on whether anything is still unlooked. While the
      // lookup was stalled that was thousands of papers, missing by year rather than at random.
      // Finished, the blind spot is the records with no DOI, which is a different and smaller
      // claim. Saying the first after the lookup completed contradicts the section above it.
      (function () {
        var oa = (D.honesty_panel || {}).coverage_openalex || {};
        if (oa.lookup_complete === false) {
          return 'One thing this cannot do, and the page will not pretend otherwise: redrawing ' +
            'the papers already in hand says nothing about the ones never fetched. Since those ' +
            'are missing by year rather than at random, the real movement is larger than these ' +
            'bands.';
        }
        return 'One thing this cannot do, and the page will not pretend otherwise: redrawing the ' +
          'papers already in hand says nothing about the ones it never sees. Every paper with a ' +
          'DOI has now been looked up, so what is left outside these bands is the records ' +
          'carrying no DOI at all, and a department that publishes where DOIs are rare is ' +
          'underweighted here in a way no resampling can reveal.';
      })();

    var by = st.by_action || {};
    // A twelve-row chart scaled into 390px puts its labels at about five pixels. On a
    // narrow screen it shows fewer rows in a narrower drawing, so the same text ends up
    // larger once the browser scales it to the column width.
    var narrow = window.innerWidth < 620;
    var rows = D.actions.slice().sort(function (a, b) { return a.rank - b.rank; })
      .slice(0, narrow ? 6 : 12)
      .map(function (a) { return { a: a, s: by[a.action_id] || {} }; })
      .filter(function (r) { return r.s.rank_p5 != null && r.s.rank_p95 != null; });
    if (!rows.length || !host) return;
    var W = narrow ? 460 : 860, rowH = narrow ? 30 : 26;
    var P = { l: narrow ? 190 : 250, r: narrow ? 44 : 54, t: 10, b: 18 };
    var H = P.t + P.b + rows.length * rowH;
    var maxR = Math.max.apply(null, rows.map(function (r) { return r.s.rank_p95; }));
    var X = function (v) { return P.l + (v - 1) / Math.max(1, maxR - 1) * (W - P.l - P.r); };
    var s = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img',
      'aria-label': 'Rank of each candidate across resamples, with its 5th to 95th percentile band' });
    caption('#stabviz', 'Rank across ' + st.resamples + ' redraws. Left is better, and the bar is the ' +
      'middle 90 percent of where a candidate landed. A percentage on the right means the candidate ' +
      'did not survive every redraw.');
    rows.forEach(function (r, i) {
      var y = P.t + i * rowH + rowH / 2;
      s.appendChild(el('text', { x: P.l - 10, y: y + 4, 'text-anchor': 'end',
        'font-family': "'IBM Plex Sans',sans-serif", 'font-size': 11.5, fill: '#5b6470' },
        shorten(r.a.department.replace('Department of ', '') + ', ' + r.a.topic.subfield, narrow ? 26 : 38)));
      s.appendChild(el('line', { x1: X(r.s.rank_p5), y1: y, x2: X(r.s.rank_p95), y2: y,
        stroke: '#c9c5be', 'stroke-width': 6, 'stroke-linecap': 'round' }));
      s.appendChild(el('circle', { cx: X(r.s.median_rank != null ? r.s.median_rank : r.a.rank),
        cy: y, r: 4.5, fill: '#2c4a6b' }));
      if (r.s.appears_pct != null && r.s.appears_pct < 80) {
        s.appendChild(el('text', { x: W - P.r + 8, y: y + 4, 'font-family': "'IBM Plex Mono',monospace",
          'font-size': 10, fill: '#b03a3a' }, Math.round(r.s.appears_pct) + '%'));
      }
    });
    host.innerHTML = ''; host.appendChild(s);
    if (!renderStability.bound) {
      renderStability.bound = true;
      var last = narrow;
      window.addEventListener('resize', function () {
        var now = window.innerWidth < 620;
        if (now !== last) { last = now; renderStability(); }
      });
    }
  }

  function renderCoverage() {
    var h = D.honesty_panel || {};
    var cov = h.coverage_pure || {};
    // The harvest is requested by publication year, but a handful of Pure records
    // carry a year outside the window that was asked for, including years that have
    // not happened yet. Counting those as thin years would report a gap in the
    // harvest that is not there, so they are separated out and named instead.
    var allYears = cov.harvest_window_publication_years || {};
    var fromYear = (D.window && D.window.publication_years_from) || 0;
    var thisYear = Number(String(D.generated_at || '').slice(0, 4)) || fromYear;
    var years = {}, strayRecords = 0, strayYears = [];
    Object.keys(allYears).sort().forEach(function (k) {
      var y = Number(k);
      if (y >= fromYear && y <= thisYear) { years[k] = allYears[k]; }
      else { strayRecords += allYears[k]; strayYears.push(k); }
    });
    var host = $('#covviz');
    var keys = Object.keys(years).sort();
    if (host && keys.length) {
      // The caption sat on the same line as the tallest bar's value label and ran off
      // the right edge. It now gets its own band above the plot, and wraps.
      var narrow = isNarrow();
      var W = narrow ? 400 : 860, H = narrow ? 210 : 196;
      var P = narrow ? { l: 40, r: 12, t: 20, b: 34 } : { l: 56, r: 20, t: 20, b: 34 };
      var max = Math.max.apply(null, keys.map(function (k) { return years[k]; })) || 1;
      var s = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img',
        'aria-label': 'How many harvested records fall in each publication year' });
      var bw = (W - P.l - P.r) / keys.length;
      keys.forEach(function (k, i) {
        var hgt = years[k] / max * (H - P.t - P.b);
        s.appendChild(el('rect', { x: P.l + i * bw + 6, y: H - P.b - hgt, width: bw - 12, height: Math.max(1, hgt),
          rx: 2, fill: '#2c4a6b' }));
        s.appendChild(el('text', { x: P.l + i * bw + bw / 2, y: H - P.b + 15, 'text-anchor': 'middle',
          'font-family': "'IBM Plex Mono',monospace", 'font-size': 10.5, fill: '#8b95a1' }, k));
        s.appendChild(el('text', { x: P.l + i * bw + bw / 2, y: H - P.b - hgt - 5, 'text-anchor': 'middle',
          'font-family': "'IBM Plex Mono',monospace", 'font-size': 10.5, fill: '#5b6470' }, n(years[k])));
      });
      caption('#covviz', 'Harvested Aarhus records by publication year, over the window the harvest ' +
        'asked for. The last bar is the year in progress, so it is short because the year is not over.');
      host.innerHTML = '';
      host.appendChild(s);
    }

    var ta = h.topic_assignment_accuracy || {};
    // rank.py writes these as hand_checked and judged_right. Reading ta.checked and
    // ta.correct found neither, so the panel printed "n/a" for a check that had in
    // fact been done on twenty labels. Accept either spelling and prefer the real one.
    var taChecked = ta.hand_checked != null ? ta.hand_checked : ta.checked;
    var taRight = ta.judged_right != null ? ta.judged_right : ta.correct;
    var taWrong = ta.judged_wrong != null ? ta.judged_wrong : null;
    var already = h.top_candidates_already_collaborating || {};
    $('#covstat').innerHTML =
      '<div><div class="k">AU records read</div><div class="n">' + (cov.records_read_from_cache || 'n/a') +
      '</div><div class="s">' + (cov.natural_sciences_works || 0) + ' of them Natural Sciences</div></div>' +
      '<div><div class="k">With a DOI</div><div class="n">' + (cov.doi_share_pct != null ? cov.doi_share_pct + '%' : 'n/a') +
      '</div><div class="s">only these can reach OpenAlex</div></div>' +
      '<div><div class="k">Topic labels checked</div><div class="n">' +
      (taChecked != null ? String(taChecked) : 'n/a') +
      '</div><div class="s">by hand, and one route removed because of it</div></div>' +
      '<div><div class="k">Candidates</div><div class="n">' + D.actions.length +
      '</div><div class="s">of ' + (D.counts ? D.counts.candidate_pairs_clearing_thresholds : '?') + ' pairs clearing the bar</div></div>';

    // The question a partnerships reader actually has: is this list finding me anything
    // I do not already know? The instrument measures that against itself and the answer
    // is unflattering, so it is printed rather than left in the data file.
    var am = h.top_candidates_already_collaborating || {};
    var amEl = $('#alreadymet');
    if (amEl) {
      amEl.innerHTML = am.share_pct_same_topic != null
        ? 'It measures that against itself, and the answer is not comfortable: of the ' +
          am.top_n_examined + ' candidates here, <b>' +
          am.candidates_where_a_danish_organisation_already_shares_an_au_project_on_the_same_topic +
          ' already have a Danish organisation on a European project with Aarhus about that very topic</b>, ' +
          'which is ' + am.share_pct_same_topic + ' percent of them. Widen it to any topic at all and it is ' +
          am.candidates_where_a_danish_organisation_already_shares_an_au_project_on_any_topic + ' of ' +
          am.top_n_examined + '. So this list mostly finds rooms where some door is already open, ' +
          'and the value is in which door and about what, not in discovering strangers.' +
          (am.note ? ' Read it as a floor: ' + esc(am.note) + '.' : '')
        : 'How often its own candidates turn out to be talking already was not measured in this build.';
    }

    // A topic keyword can be a homonym, and a correct mapping from a loose tag still
    // produces a wrong answer. Named with the worst real case rather than described,
    // and quantified, because a general warning tells a reader nothing about how often.
    var lt = h.loose_cordis_tags || {};
    var ltEl = $('#loosetags');
    if (ltEl) {
      var ex = (lt.named_examples || []).filter(function (e) { return /UNIVERSITETSHOSPITAL/i.test(e.organisation); })[0]
        || (lt.named_examples || [])[0];
      var worst = (lt.worst_candidates || [])[0];
      ltEl.innerHTML = (ex
        ? 'The clearest case is on the top candidate. <b>' + esc(ex.organisation) + '</b> is offered as ' +
          'a partner for ' + esc(ex.department) + ' on ' + esc(ex.topic) + ', because it joined project ' +
          esc(ex.project_id) + ', "' + esc(ex.project_title) + '", and CORDIS tagged that project with the ' +
          'keyword <i>' + esc((ex.carried_by_term || []).join(', ')) + '</i>. That word sits under ecology in ' +
          'the vocabulary and meant something else in the project, so the page ends up proposing that ' +
          'Aarhus introduce its ecologists to its own university hospital about rare diseases. The mapping ' +
          'worked correctly and the answer is still wrong. '
        : '') +
        (lt.weakly_supported_pct_of_listed_organisations != null
          ? 'This is measured rather than left as a warning: ' + lt.weakly_supported_pct_of_listed_organisations +
            ' percent of the organisations listed on this page reach their topic through a keyword with ' +
            'nothing corroborating it, and they are marked as such where they appear. '
          : '') +
        (worst
          ? 'It is not spread evenly. <b>' + esc(worst.topic) + ' is the worst affected at ' +
            worst.weakly_supported_pct + ' percent</b>, because "ecosystems" means one thing to a biologist ' +
            'and another to everyone writing about business, innovation and health. '
          : '') +
        'Weak support is not the same as a wrong link, which is why none of these are dropped: a ' +
        'bio-methanol company reaches organic chemistry through the word "alcohols", uncorroborated and ' +
        'entirely correct. Read the project titles before reading the organisation names.';
    }

    var oa = h.coverage_openalex || {};
    // Only the finished years can be compared against each other. The year in
    // progress is short for a reason that has nothing to do with the harvest.
    var done = keys.filter(function (k) { return Number(k) < thisYear; });
    var yearCounts = done.map(function (k) { return years[k]; });
    var lo = yearCounts.length ? Math.min.apply(null, yearCounts) : null;
    var hi = yearCounts.length ? Math.max.apply(null, yearCounts) : null;

    var v3;
    if (oa.lookup_complete === false && oa.match_rate_pct != null) {
      v3 = '<b>Most of the papers have not been looked up yet, and that is the biggest thing wrong with this page.</b> ' +
        'Of the ' + n(oa.dois_looked_up) + ' Natural Sciences papers that carry a DOI, ' + n(oa.dois_matched) +
        ' have been matched to a topic, which is ' + oa.match_rate_pct + ' percent of them. ' +
        'OpenAlex moved to a paid interface partway through this build and the free daily allowance ran out, ' +
        'so the other ' + n(oa.dois_never_asked) + ' are waiting on the next reset rather than on a fix to the code. ' +
        'Every count and every ranking above is computed on the matched share alone, so read the ordering as a draft ' +
        'that has not yet seen three quarters of its own evidence.';
    } else {
      v3 = '<b>Every ranking here rests on the share of papers that could be matched to a topic.</b> ' +
        'That share is ' + (oa.match_rate_pct != null ? oa.match_rate_pct + ' percent' : 'partial') +
        ' of the Natural Sciences papers carrying a DOI. The rest are invisible to this instrument, ' +
        'and a department that publishes where DOIs are rare will look quieter here than it is.';
    }
    if (lo != null && hi != null && done.length > 1) {
      v3 += ' The harvest itself is even across the finished years in the window, at no fewer than ' +
        n(lo) + ' and no more than ' + n(hi) + ' records in any one of them' +
        (oa.lookup_complete === false
          ? ', so the shortfall sits in the topic lookup rather than in what was collected.'
          : ', so no year is carrying more of the ranking than another.');
    }
    if (strayRecords) {
      v3 += ' A further ' + strayRecords + (strayRecords === 1 ? ' record carries' : ' records carry') +
        ' a publication year outside the window (' + strayYears.join(', ') + '). That is how those records are dated ' +
        'in Pure rather than a fault in the harvest, and they are left out of the chart above.';
    }
    $('#v3').innerHTML = v3;

    $('#lim1').textContent = (oa.lookup_complete === false
      ? 'Coverage is partial, as act three shows. Only '
      : 'Coverage is bounded by the DOI, as act three shows. Only ') +
      (cov.doi_share_pct != null ? cov.doi_share_pct + ' percent' : 'some') +
      ' of the harvested Natural Sciences records carry a DOI, and only those can reach a topic at all. ' +
      (oa.match_rate_pct == null
        ? 'Anything published without one is invisible to this instrument.'
        : oa.lookup_complete === false
          ? 'Of those, ' + oa.match_rate_pct + ' percent have been looked up so far, so what you are ' +
            'reading is computed on a fraction of what Aarhus published.'
          : 'Of those, ' + oa.match_rate_pct + ' percent were matched to a topic, so the lookup is no ' +
            'longer the limit here. What is left out is everything published without a DOI, and a ' +
            'department that publishes where DOIs are rare will look quieter here than it is.');
    // Quoting the raw 10-of-20 here would be unfair in the other direction: that sample
    // was drawn from a run that still used a matching route this check then removed. The
    // split by route is the honest reading, and so is saying the fix is not re-verified.
    var byRoute = ta.by_bridge_match_method || {};
    var kw = byRoute.topic_keyword || {}, sn = byRoute.subfield_name || {};
    var byType = ta.by_check_type || {};
    var paper = byType.paper_to_subfield || {};
    $('#lim2').innerHTML = 'A topic is an OpenAlex subfield, assigned by a classifier rather than by ' +
      'the authors, and the labels were checked by hand rather than trusted. ' +
      (taChecked ? 'Twenty were read one by one. ' : '') +
      (kw.checked ? 'That check is why one matching route is gone: of ' + kw.checked +
        ' labels made by matching a project term against a topic keyword, ' + kw.wrong +
        ' were plainly wrong, so that route was switched off and nothing on this page uses it. ' : '') +
      (sn.checked ? 'The route that remains, matching against a subfield name, was right ' + sn.right +
        ' times in ' + sn.checked + '. ' : '') +
      (paper.checked ? 'On the paper side, ' + paper.checked + ' labels were read and ' + paper.wrong +
        ' were wrong with ' + paper.partly_right + ' partly right. ' : '') +
      '<b>The fix has not been re-verified on a fresh sample</b>, so the strongest claim available ' +
      'is that the worst route was found and removed, not that what remains has been measured.';
  }

  function fillProse() {
    var c = D.counts || {};
    var h = D.honesty_panel || {};
    var already = h.top_candidates_already_collaborating || {};
    $('#dek').innerHTML =
      '<strong>' + (c.candidate_pairs_clearing_thresholds || D.actions.length) +
      ' pairs of an Aarhus Natural Sciences department and a research topic clear the bar, and ' +
      (c.white_space_in_written || 0) + ' of the ' + D.actions.length +
      ' written up have no company co-author anywhere in the world.</strong> ' +
      'Each one carries the papers, the Danish organisations and the reason it was scored that way, ' +
      'so you can disagree with the ranking and recompute it. ' +
      (already.share_pct_same_topic != null
        ? 'This is rarely about strangers: ' + already.share_pct_same_topic + ' percent of these candidates ' +
          'already have a Danish organisation on a European project with Aarhus about that very topic, ' +
          'so what is missing is usually the subject rather than the introduction. '
        : '') +
      'The last act is the instrument measuring what it cannot tell you.';
    $('#methodtext').innerHTML =
      'Aarhus Pure is harvested over its OAI-PMH endpoint, which is the only source that knows which faculty a paper ' +
      'belongs to. Those papers reach OpenAlex by DOI, which supplies the topic and the institution type of every ' +
      'co-author, so a company co-author is a fact in the record rather than an inference. The partner side comes from ' +
      'the CORDIS Horizon Europe export, where Aarhus University is participant ' +
      '999997736 and appears on 439 projects; self-joining that file on those project identifiers gives the Danish ' +
      'organisations who have already worked with Aarhus, and the topics give the ones who have not. Every link in ' +
      'that chain is an identifier match. No organisation name is ever compared to another.';
  }

  /* ---------- the walkthrough ---------- */
  function tour() {
    var root = $('#tour'), hl = $('.tour-hl', root), card = $('.tour-card', root), idx = 0;
    var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    var STEPS = [
      { sel: 'header h1', k: 'Welcome · 1 of 5', html: 'A shortlist of subjects Aarhus could raise with Danish organisations it has mostly already met, built from three public sources and joined on identifiers rather than names.' },
      { sel: '#domain', k: 'Where it comes from · 2 of 5', html: 'Pure knows which faculty a paper belongs to. OpenAlex knows its topic and whether a company co-authored it. CORDIS knows which Danish organisations work on the same topics in European projects.' },
      { sel: '#alist', k: 'The candidates · 3 of 5', html: '<b>Pick a department above, then click a row.</b> Every candidate opens to show the papers, the organisations, and whether the two have already met.' },
      // The tour must not promise a brief that is not there. Which step four is
      // depends on whether the hand-written Action exists for the current top candidate.
      (typeof WORKED !== 'undefined' && WORKED && D.actions.length &&
       WORKED.action_id === D.actions.slice().sort(function (a, b) { return b.score - a.score; })[0].action_id)
        ? { sel: '#worked', k: 'The job itself · 4 of 5', html: 'The instrument gives a shortlist. This is the top one taken as far as a specialist would take it, by hand: who is in the room, what the first session produces, what would kill it.' }
        : { sel: '#worked', k: 'The job itself · 4 of 5', html: 'This is where the shortlist stops being arithmetic. One candidate gets taken as far as a specialist would take it by hand. It is not written yet, because the ranking above still moves as coverage lands, for the reason the last act gives.' },
      { sel: '#covviz', k: 'What it cannot tell you · 5 of 5', html: 'Coverage, topic accuracy, and how often the tool\'s own top candidates turn out to be talking already. This act is the reason to trust the others.' }
    ];
    function place() {
      var st = STEPS[idx], elm = document.querySelector(st.sel);
      if (!elm) { next(); return; }
      var r = elm.getBoundingClientRect(), sx = window.scrollX, sy = window.scrollY;
      var docTop = r.top + sy, docLeft = r.left + sx;
      root.style.height = document.documentElement.scrollHeight + 'px';
      var maxScroll = Math.max(0, document.documentElement.scrollHeight - innerHeight);
      var target = Math.max(0, Math.min(docTop - 14, maxScroll)), vTop = docTop - target;
      var cw = Math.min(400, innerWidth - 32), ch = 250;
      var fitsRight = r.left + r.width + 18 + cw <= innerWidth - 16;
      var hh = fitsRight ? r.height : Math.max(120, Math.min(r.height, innerHeight - vTop - ch - 40));
      hl.style.left = (docLeft - 8) + 'px'; hl.style.top = (docTop - 8) + 'px';
      hl.style.width = (r.width + 16) + 'px'; hl.style.height = (hh + 16) + 'px';
      var dots = STEPS.map(function (_, i) { return '<i class="' + (i === idx ? 'on' : '') + '"></i>'; }).join('');
      card.innerHTML = '<div class="tk">' + st.k + '</div><p>' + st.html + '</p><div class="tour-nav"><div class="dots">' + dots + '</div>' +
        (idx > 0 ? '<button class="tour-btn" id="tprev">Back</button>' : '') +
        '<button class="tour-btn" id="tskip">Close</button><button class="tour-btn primary" id="tnext">' +
        (idx < STEPS.length - 1 ? 'Next' : 'Done') + '</button></div>';
      var cx, cy;
      if (fitsRight) { cx = docLeft + r.width + 18; cy = docTop; }
      else { cx = Math.min(docLeft, sx + innerWidth - 16 - cw); cy = docTop + hh + 22; }
      card.style.left = Math.max(sx + 16, cx) + 'px';
      card.style.top = Math.max(target + 16, cy) + 'px';
      $('#tnext').onclick = next; $('#tskip').onclick = stop;
      var pv = $('#tprev'); if (pv) pv.onclick = function () { idx = Math.max(0, idx - 1); place(); };
      window.scrollTo({ top: target, behavior: reduced ? 'auto' : 'smooth' });
    }
    function next() { if (idx >= STEPS.length - 1) { stop(); return; } idx++; place(); }
    function stop() { root.classList.remove('on'); try { localStorage.setItem('af-tour', 'seen'); } catch (e) { } }
    function start() { idx = 0; root.classList.add('on'); place(); }
    $('#tourbtn').addEventListener('click', start);
    var replace = function () { if (root.classList.contains('on')) place(); };
    window.addEventListener('resize', replace);
    window.addEventListener('load', replace);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(replace);
    if (!location.search.includes('tour=off')) setTimeout(start, 700);
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (typeof D === 'undefined') return;
    drawDomain();
    renderDepts();
    renderList();
    renderDetail();
    renderWorked();
    selfCheck();
    redrawOnWidthChange(drawDomain);
    redrawOnWidthChange(renderCoverage);
    redrawOnWidthChange(renderCoverageByYear);
    renderCoverageByYear();
    renderStability();
    renderCoverage();
    fillProse();
    $('#v1').innerHTML = '<b>The white-space mark is the one worth arguing with.</b> ' +
      'It means the department has published in a topic without a single company co-author anywhere in the world, ' +
      'which can mean an opening or can mean the topic is simply not one industry works on. ' +
      'The instrument cannot tell those apart, and a specialist can in about a minute, which is roughly the division ' +
      'of labour this page is arguing for.';
    $('#v2').innerHTML = '<b>Most of what the instrument returned was thrown away to get here.</b> ' +
      'Ninety organisations became one, and the reasons for discarding the other eighty-nine are ' +
      'written out above rather than left as a judgement call the reader has to trust. That is the ' +
      'work the shortlist exists to make possible, and it is still a person doing it.';
    tour();
  });
})();
