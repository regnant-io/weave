// A tiny, total expression language for simulation specs.
//
// Simulations are the one place a spec genuinely needs to express MATH — "y =
// v0*sin(theta)*t - 0.5*g*t^2" cannot be enumerated as data. The obvious
// implementation is eval(), and that is exactly what we are not going to do:
// these expressions are written by a language model and rendered inside a page
// the user trusts, so they must be incapable of reaching anything but numbers.
//
// This is a recursive-descent parser over a fixed grammar. There is no property
// access, no function values, no assignment, no strings — the only things that
// exist are numbers, named parameters, and a whitelist of math functions. A
// malformed or hostile expression can fail to parse; it cannot escape.
//
// The same source runs server-side (to validate a spec before we persist it)
// and inside the generated page (to evaluate per frame), so it is authored once
// here as a string and shared by both.

export const EXPR_RUNTIME = String.raw`
(function (root) {
  var FUNCS = {
    sin: Math.sin, cos: Math.cos, tan: Math.tan,
    asin: Math.asin, acos: Math.acos, atan: Math.atan, atan2: Math.atan2,
    sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
    exp: Math.exp, sqrt: Math.sqrt, abs: Math.abs,
    log: Math.log, ln: Math.log, log10: Math.log10, log2: Math.log2,
    floor: Math.floor, ceil: Math.ceil, round: Math.round, sign: Math.sign,
    min: Math.min, max: Math.max, pow: Math.pow, hypot: Math.hypot,
    mod: function (a, b) { return ((a % b) + b) % b; },
    clamp: function (x, a, b) { return Math.min(Math.max(x, a), b); },
    lerp: function (a, b, t) { return a + (b - a) * t; },
    step: function (edge, x) { return x < edge ? 0 : 1; },
    gauss: function (x, mu, s) {
      var d = (x - (mu || 0)) / (s || 1);
      return Math.exp(-0.5 * d * d) / ((s || 1) * Math.sqrt(2 * Math.PI));
    }
  };
  var CONSTS = { pi: Math.PI, PI: Math.PI, e: Math.E, E: Math.E, tau: 2 * Math.PI, inf: Infinity };

  function tokenize(src) {
    var out = [], i = 0, s = String(src);
    while (i < s.length) {
      var c = s[i];
      if (/\s/.test(c)) { i++; continue; }
      if (/[0-9.]/.test(c)) {
        var j = i; while (j < s.length && /[0-9.eE]/.test(s[j])) {
          // allow exponent sign only directly after e/E
          if ((s[j] === 'e' || s[j] === 'E') && /[+\-]/.test(s[j + 1] || '')) j++;
          j++;
        }
        var num = parseFloat(s.slice(i, j));
        if (!isFinite(num)) throw new Error('bad number at ' + i);
        out.push({ t: 'num', v: num }); i = j; continue;
      }
      if (/[A-Za-z_]/.test(c)) {
        var k = i; while (k < s.length && /[A-Za-z0-9_]/.test(s[k])) k++;
        out.push({ t: 'id', v: s.slice(i, k) }); i = k; continue;
      }
      var two = s.slice(i, i + 2);
      if (two === '<=' || two === '>=' || two === '==' || two === '!=' || two === '&&' || two === '||') {
        out.push({ t: 'op', v: two }); i += 2; continue;
      }
      if ('+-*/%^(),<>?:'.indexOf(c) >= 0) { out.push({ t: 'op', v: c }); i++; continue; }
      throw new Error('unexpected character ' + JSON.stringify(c));
    }
    return out;
  }

  function parse(src) {
    var toks = tokenize(src), pos = 0;
    function peek() { return toks[pos]; }
    function eat(v) {
      var t = toks[pos];
      if (!t || (v !== undefined && t.v !== v)) throw new Error('expected ' + v);
      pos++; return t;
    }
    // precedence climbing
    function parseExpr() { return parseTernary(); }
    function parseTernary() {
      var c = parseOr();
      if (peek() && peek().v === '?') {
        eat('?'); var a = parseExpr(); eat(':'); var b = parseExpr();
        return function (s) { return c(s) ? a(s) : b(s); };
      }
      return c;
    }
    function binary(next, ops) {
      return function () {
        var left = next();
        while (peek() && peek().t === 'op' && ops.indexOf(peek().v) >= 0) {
          var op = eat().v, right = next();
          left = (function (l, r, o) {
            return function (s) {
              var a = l(s), b = r(s);
              switch (o) {
                case '+': return a + b; case '-': return a - b;
                case '*': return a * b; case '/': return a / b;
                case '%': return ((a % b) + b) % b;
                case '<': return a < b ? 1 : 0; case '>': return a > b ? 1 : 0;
                case '<=': return a <= b ? 1 : 0; case '>=': return a >= b ? 1 : 0;
                case '==': return a === b ? 1 : 0; case '!=': return a !== b ? 1 : 0;
                case '&&': return (a && b) ? 1 : 0; case '||': return (a || b) ? 1 : 0;
              }
              return NaN;
            };
          })(left, right, op);
        }
        return left;
      };
    }
    var parseCmp = binary(function () { return parseAdd(); }, ['<', '>', '<=', '>=', '==', '!=']);
    var parseAnd = binary(function () { return parseCmp(); }, ['&&']);
    var parseOr = binary(function () { return parseAnd(); }, ['||']);
    function parseAdd() {
      var left = parseMul();
      while (peek() && (peek().v === '+' || peek().v === '-')) {
        var op = eat().v, right = parseMul();
        left = (function (l, r, o) {
          return function (s) { return o === '+' ? l(s) + r(s) : l(s) - r(s); };
        })(left, right, op);
      }
      return left;
    }
    function parseMul() {
      var left = parseUnary();
      while (peek() && (peek().v === '*' || peek().v === '/' || peek().v === '%')) {
        var op = eat().v, right = parseUnary();
        left = (function (l, r, o) {
          return function (s) {
            var a = l(s), b = r(s);
            return o === '*' ? a * b : o === '/' ? a / b : ((a % b) + b) % b;
          };
        })(left, right, op);
      }
      return left;
    }
    function parseUnary() {
      if (peek() && (peek().v === '-' || peek().v === '+')) {
        var op = eat().v, v = parseUnary();
        return op === '-' ? function (s) { return -v(s); } : v;
      }
      return parsePow();
    }
    function parsePow() {
      var base = parseAtom();
      if (peek() && peek().v === '^') {
        eat('^');
        var exp = parseUnary(); // right-associative
        return function (s) { return Math.pow(base(s), exp(s)); };
      }
      return base;
    }
    function parseAtom() {
      var t = peek();
      if (!t) throw new Error('unexpected end of expression');
      if (t.t === 'num') { eat(); return function () { return t.v; }; }
      if (t.t === 'id') {
        eat();
        var name = t.v;
        if (peek() && peek().v === '(') {
          eat('(');
          var args = [];
          if (peek() && peek().v !== ')') {
            args.push(parseExpr());
            while (peek() && peek().v === ',') { eat(','); args.push(parseExpr()); }
          }
          eat(')');
          var fn = FUNCS[name];
          if (!fn) throw new Error('unknown function ' + name);
          return function (s) {
            var vals = new Array(args.length);
            for (var i = 0; i < args.length; i++) vals[i] = args[i](s);
            return fn.apply(null, vals);
          };
        }
        if (Object.prototype.hasOwnProperty.call(CONSTS, name)) {
          var cv = CONSTS[name];
          return function () { return cv; };
        }
        // Unknown identifiers resolve from the scope object at call time and
        // default to 0, so a spec that references a parameter it forgot to
        // declare renders a flat line instead of throwing mid-frame.
        // Own-properties only: without this, an identifier like "constructor"
        // would read up the prototype chain. It could still only ever yield a
        // number thanks to the typeof guard, but not reading at all is better.
        return function (s) {
          if (!s || !Object.prototype.hasOwnProperty.call(s, name)) return 0;
          var v = s[name];
          return typeof v === 'number' ? v : 0;
        };
      }
      if (t.v === '(') { eat('('); var inner = parseExpr(); eat(')'); return inner; }
      throw new Error('unexpected token ' + JSON.stringify(t.v));
    }

    var fn = parseExpr();
    if (pos !== toks.length) throw new Error('trailing input in expression');
    return fn;
  }

  root.WeaveExpr = {
    compile: function (src) {
      try {
        var f = parse(src);
        return { ok: true, fn: f };
      } catch (e) {
        return { ok: false, error: String(e && e.message ? e.message : e) };
      }
    },
    // Never throws — a broken expression yields NaN, which plots as a gap.
    safe: function (src) {
      var c = root.WeaveExpr.compile(src);
      if (!c.ok) return function () { return NaN; };
      return function (scope) {
        try { var v = c.fn(scope); return typeof v === 'number' ? v : NaN; }
        catch (e) { return NaN; }
      };
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
`;

// Server-side copy, used to validate specs before they are persisted. The input
// is our own constant above, never caller data.
const scope = {};
new Function(EXPR_RUNTIME).call(scope);
// eslint-disable-next-line no-undef
export const WeaveExpr = globalThis.WeaveExpr;

/** Validate every expression in a list. Returns the first error, or null. */
export function validateExpressions(list) {
  for (const src of list) {
    if (typeof src !== "string" || !src.trim()) continue;
    const r = WeaveExpr.compile(src);
    if (!r.ok) return `"${String(src).slice(0, 60)}": ${r.error}`;
  }
  return null;
}
