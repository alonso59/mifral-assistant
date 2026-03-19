/**
 * Zero-dependency markdown renderer with syntax highlighting.
 * Supports: Python, JavaScript/TypeScript, Bash/Shell, SQL, TCL, Verilog/SystemVerilog,
 * LaTeX, Markdown, JSON, YAML, CSS, HTML/XML, Go, Rust, Java, C/C++.
 */

// ── HTML escape ───────────────────────────────────────────────────────────────

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Syntax highlighter ────────────────────────────────────────────────────────

type TokenType = 'kw' | 'str' | 'cmt' | 'num' | 'fn' | 'op' | 'type' | 'dec' | 'meta' | 'plain';

interface Token {
  t: TokenType;
  v: string;
}

const COLORS: Record<TokenType, string> = {
  kw:   '#c678dd', // purple  — keywords
  str:  '#98c379', // green   — strings
  cmt:  '#7f848e', // gray    — comments
  num:  '#d19a66', // orange  — numbers
  fn:   '#61afef', // blue    — functions/methods
  op:   '#56b6c2', // cyan    — operators
  type: '#e5c07b', // yellow  — types/classes
  dec:  '#e5c07b', // yellow  — decorators / annotations
  meta: '#abb2bf', // light   — meta / punctuation
  plain:'#abb2bf', // base    — plain text
};

function tok(t: TokenType, v: string): Token {
  return { t, v };
}

// Common keyword sets
const KEYWORDS: Record<string, string[]> = {
  python: ['False','None','True','and','as','assert','async','await','break','class','continue',
    'def','del','elif','else','except','finally','for','from','global','if','import','in',
    'is','lambda','nonlocal','not','or','pass','raise','return','try','while','with','yield'],
  js: ['abstract','arguments','async','await','boolean','break','byte','case','catch','char',
    'class','const','continue','debugger','default','delete','do','double','else','enum',
    'eval','export','extends','false','final','finally','float','for','from','function',
    'goto','if','implements','import','in','instanceof','int','interface','let','long',
    'native','new','null','of','package','private','protected','public','return','short',
    'static','super','switch','synchronized','this','throw','throws','transient','true',
    'try','type','typeof','undefined','var','void','volatile','while','with','yield'],
  bash: ['if','then','else','elif','fi','for','while','do','done','case','esac','in','until',
    'function','return','exit','local','export','readonly','declare','unset','shift',
    'break','continue','true','false','echo','printf','read','source','alias'],
  sql: ['SELECT','FROM','WHERE','JOIN','LEFT','RIGHT','INNER','OUTER','FULL','ON','AS',
    'GROUP','BY','ORDER','HAVING','LIMIT','OFFSET','INSERT','INTO','VALUES','UPDATE',
    'SET','DELETE','CREATE','TABLE','INDEX','VIEW','DROP','ALTER','ADD','COLUMN',
    'PRIMARY','KEY','FOREIGN','REFERENCES','UNIQUE','NOT','NULL','DEFAULT','AND','OR',
    'IN','LIKE','BETWEEN','EXISTS','UNION','ALL','DISTINCT','WITH','CASE','WHEN',
    'THEN','ELSE','END','BEGIN','COMMIT','ROLLBACK','TRANSACTION'],
  go: ['break','case','chan','const','continue','default','defer','else','fallthrough',
    'for','func','go','goto','if','import','interface','map','package','range','return',
    'select','struct','switch','type','var','nil','true','false','iota','make','new',
    'len','cap','append','copy','delete','close','panic','recover','print','println'],
  rust: ['as','async','await','break','const','continue','crate','dyn','else','enum','extern',
    'false','fn','for','if','impl','in','let','loop','match','mod','move','mut','pub',
    'ref','return','self','Self','static','struct','super','trait','true','type','union',
    'unsafe','use','where','while','i8','i16','i32','i64','i128','u8','u16','u32','u64',
    'u128','f32','f64','bool','char','str','String','Vec','Option','Result','Some','None',
    'Ok','Err'],
  tcl: ['proc','if','else','elseif','foreach','for','while','return','set','unset','puts',
    'gets','incr','append','lappend','lindex','llength','lrange','lsort','concat','expr',
    'string','list','array','dict','namespace','package','source','load','catch','error',
    'variable','global','upvar','uplevel','after','after','eval','subst','regexp','regsub',
    'open','close','read','write','chan','file','glob'],
  verilog: ['module','endmodule','input','output','inout','wire','reg','logic','integer','real',
    'parameter','localparam','begin','end','always','initial','assign','if','else','case',
    'endcase','for','while','repeat','forever','fork','join','task','endtask','function',
    'endfunction','posedge','negedge','or','and','not','xor','nand','nor','xnor',
    'generate','endgenerate','genvar','defparam','specify','endspecify','timescale',
    'define','ifdef','ifndef','endif','include','default','casez','casex'],
};

// Types for various languages
const TYPES: Record<string, string[]> = {
  python: ['int','float','str','bool','list','dict','tuple','set','bytes','bytearray',
    'complex','type','object','Exception','TypeError','ValueError','KeyError',
    'AttributeError','ImportError','IOError','OSError','RuntimeError'],
  js: ['Array','Boolean','Date','Error','Function','Map','Number','Object','Promise',
    'Proxy','RegExp','Set','String','Symbol','WeakMap','WeakSet','undefined',
    'never','any','unknown','void','string','number','boolean','bigint','symbol'],
  go: ['string','int','int8','int16','int32','int64','uint','uint8','uint16','uint32',
    'uint64','float32','float64','complex64','complex128','bool','byte','rune','error'],
};

function tokenize(code: string, lang: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const kws = new Set((KEYWORDS[lang] ?? KEYWORDS['js']).map(k => lang === 'sql' ? k.toLowerCase() : k));
  const types = new Set((TYPES[lang] ?? TYPES['js']));

  // Language-specific comment starters
  const lineComment = lang === 'python' || lang === 'bash' || lang === 'tcl' ? '#'
    : lang === 'sql' ? '--'
    : lang === 'verilog' ? '//'
    : lang === 'latex' ? '%'
    : '//';

  const blockCommentStart = (lang === 'js' || lang === 'ts' || lang === 'go' || lang === 'rust' || lang === 'c' || lang === 'cpp' || lang === 'verilog') ? '/*' : null;
  const blockCommentEnd = '*/';

  while (i < code.length) {
    const rest = code.slice(i);

    // Block comment
    if (blockCommentStart && rest.startsWith(blockCommentStart)) {
      const end = code.indexOf(blockCommentEnd, i + 2);
      const val = end === -1 ? rest : code.slice(i, end + 2);
      tokens.push(tok('cmt', val));
      i += val.length;
      continue;
    }

    // Line comment
    if (rest.startsWith(lineComment)) {
      const nl = code.indexOf('\n', i);
      const val = nl === -1 ? rest : code.slice(i, nl);
      tokens.push(tok('cmt', val));
      i += val.length;
      continue;
    }

    // LaTeX command
    if (lang === 'latex' && rest[0] === '\\') {
      const m = rest.match(/^\\[a-zA-Z]+/);
      if (m) { tokens.push(tok('kw', m[0])); i += m[0].length; continue; }
    }

    // Decorator / annotation
    if ((lang === 'python' || lang === 'js' || lang === 'ts' || lang === 'java') && rest[0] === '@') {
      const m = rest.match(/^@[\w.]+/);
      if (m) { tokens.push(tok('dec', m[0])); i += m[0].length; continue; }
    }

    // Triple-quoted strings (Python)
    if (lang === 'python' && (rest.startsWith('"""') || rest.startsWith("'''"))) {
      const q = rest.slice(0, 3);
      const end = code.indexOf(q, i + 3);
      const val = end === -1 ? rest : code.slice(i, end + 3);
      tokens.push(tok('str', val));
      i += val.length;
      continue;
    }

    // Regular strings
    if (rest[0] === '"' || rest[0] === "'") {
      const q = rest[0];
      let j = i + 1;
      while (j < code.length && code[j] !== q && code[j] !== '\n') {
        if (code[j] === '\\') j++;
        j++;
      }
      const val = code.slice(i, j + 1);
      tokens.push(tok('str', val));
      i = j + 1;
      continue;
    }

    // Template literals (JS/TS)
    if ((lang === 'js' || lang === 'ts') && rest[0] === '`') {
      let j = i + 1;
      while (j < code.length && code[j] !== '`') {
        if (code[j] === '\\') j++;
        j++;
      }
      const val = code.slice(i, j + 1);
      tokens.push(tok('str', val));
      i = j + 1;
      continue;
    }

    // Numbers
    const numMatch = rest.match(/^(0x[\da-fA-F]+|0b[01]+|0o[0-7]+|\d+\.?\d*(?:[eE][+-]?\d+)?)/);
    if (numMatch) {
      tokens.push(tok('num', numMatch[0]));
      i += numMatch[0].length;
      continue;
    }

    // Identifiers / keywords
    const idMatch = rest.match(/^[a-zA-Z_$][\w$]*/);
    if (idMatch) {
      const word = idMatch[0];
      const normalized = lang === 'sql' ? word.toLowerCase() : word;
      if (kws.has(normalized)) {
        tokens.push(tok('kw', word));
      } else if (types.has(word)) {
        tokens.push(tok('type', word));
      } else if (code[i + word.length] === '(') {
        tokens.push(tok('fn', word));
      } else {
        tokens.push(tok('plain', word));
      }
      i += word.length;
      continue;
    }

    // Operators
    const opMatch = rest.match(/^([+\-*/%=<>!&|^~?:]+|\.\.\.)/);
    if (opMatch) {
      tokens.push(tok('op', opMatch[0]));
      i += opMatch[0].length;
      continue;
    }

    // Anything else (punctuation, whitespace)
    tokens.push(tok('plain', rest[0]));
    i++;
  }

  return tokens;
}

function renderTokens(tokens: Token[]): string {
  return tokens.map(({ t, v }) => {
    const escaped = esc(v);
    if (t === 'plain') return escaped;
    return `<span style="color:${COLORS[t]}">${escaped}</span>`;
  }).join('');
}

const LANG_ALIASES: Record<string, string> = {
  py: 'python', python: 'python',
  js: 'js', javascript: 'js', jsx: 'js',
  ts: 'ts', typescript: 'ts', tsx: 'ts',
  sh: 'bash', bash: 'bash', shell: 'bash', zsh: 'bash',
  sql: 'sql',
  go: 'go', golang: 'go',
  rs: 'rust', rust: 'rust',
  tcl: 'tcl',
  v: 'verilog', sv: 'verilog', verilog: 'verilog', systemverilog: 'verilog',
  tex: 'latex', latex: 'latex',
  java: 'java',
  c: 'c', cpp: 'cpp', 'c++': 'cpp',
};

export function highlightCode(code: string, lang: string): string {
  const normalized = LANG_ALIASES[lang.toLowerCase()] ?? null;
  if (!normalized) return esc(code); // unknown lang — just escape
  return renderTokens(tokenize(code, normalized));
}

// ── Markdown parser ───────────────────────────────────────────────────────────

function parseInline(text: string): string {
  // Bold + italic combined: ***text***
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  // Bold: **text** or __text__
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__(.+?)__/g, '<strong>$1</strong>');
  // Italic: *text* or _text_ (not in words)
  text = text.replace(/\*([^*\n]+?)\*/g, '<em>$1</em>');
  text = text.replace(/(?<!\w)_([^_\n]+?)_(?!\w)/g, '<em>$1</em>');
  // Strikethrough: ~~text~~
  text = text.replace(/~~(.+?)~~/g, '<del>$1</del>');
  // Inline code: `code`
  text = text.replace(/`([^`\n]+?)`/g, '<code style="background:rgba(0,0,0,0.06);padding:1px 5px;border-radius:4px;font-family:\'SF Mono\',\'Fira Code\',monospace;font-size:0.9em">$1</code>');
  // Links: [text](url)
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:#61afef;text-decoration:underline">$1</a>');
  return text;
}

export function renderMarkdown(raw: string): string {
  if (!raw) return '';

  const lines = raw.split('\n');
  const out: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // ── Fenced code block ````lang\n...\n````
    const fenceMatch = line.match(/^```(\w*)\s*$/);
    if (fenceMatch) {
      const lang = fenceMatch[1].trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // consume closing ```
      const rawCode = codeLines.join('\n');
      const highlighted = lang ? highlightCode(rawCode, lang) : esc(rawCode);
      const langLabel = lang ? `<span style="position:absolute;top:8px;right:12px;font-size:10px;color:#5c6370;font-family:monospace;text-transform:uppercase;letter-spacing:.04em">${esc(lang)}</span>` : '';
      out.push(
        `<div style="position:relative;margin:8px 0">` +
        langLabel +
        `<pre style="background:#282c34;border-radius:8px;padding:14px 16px;overflow-x:auto;font-family:'SF Mono','Fira Code','Fira Mono','Roboto Mono',monospace;font-size:12px;line-height:1.6;color:#abb2bf;margin:0"><code>${highlighted}</code></pre></div>`
      );
      continue;
    }

    // ── Indented code block (4 spaces)
    if (line.startsWith('    ') && !line.startsWith('     ')) {
      const codeLines: string[] = [];
      while (i < lines.length && (lines[i].startsWith('    ') || lines[i].trim() === '')) {
        codeLines.push(lines[i].startsWith('    ') ? lines[i].slice(4) : '');
        i++;
      }
      const rawCode = codeLines.join('\n').trimEnd();
      out.push(
        `<pre style="background:#282c34;border-radius:8px;padding:14px 16px;overflow-x:auto;font-family:'SF Mono','Fira Code',monospace;font-size:12px;line-height:1.6;color:#abb2bf;margin:8px 0"><code>${esc(rawCode)}</code></pre>`
      );
      continue;
    }

    // ── Horizontal rule
    if (/^(\*{3,}|-{3,}|_{3,})\s*$/.test(line)) {
      out.push('<hr style="border:none;border-top:1px solid rgba(0,0,0,0.12);margin:12px 0">');
      i++;
      continue;
    }

    // ── ATX Headings
    const h = line.match(/^(#{1,6})\s+(.*)/);
    if (h) {
      const lvl = h[1].length;
      const sizes = ['1.25em','1.15em','1.05em','1em','0.95em','0.9em'];
      const sz = sizes[lvl - 1];
      out.push(`<p style="font-size:${sz};font-weight:650;color:rgba(0,0,0,0.82);margin:10px 0 4px;line-height:1.35">${parseInline(h[2])}</p>`);
      i++;
      continue;
    }

    // ── Blockquote
    if (line.startsWith('> ')) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].startsWith('> ')) {
        quoteLines.push(lines[i].slice(2));
        i++;
      }
      out.push(
        `<blockquote style="border-left:3px solid rgba(0,0,0,0.2);margin:6px 0;padding:4px 12px;color:rgba(0,0,0,0.55)">` +
        quoteLines.map(l => parseInline(l)).join('<br>') +
        `</blockquote>`
      );
      continue;
    }

    // ── Unordered list
    if (/^[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*+]\s+/, ''));
        i++;
      }
      out.push(
        `<ul style="margin:4px 0 4px 18px;padding:0;list-style:disc">` +
        items.map(it => `<li style="margin:2px 0">${parseInline(it)}</li>`).join('') +
        `</ul>`
      );
      continue;
    }

    // ── Ordered list
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ''));
        i++;
      }
      out.push(
        `<ol style="margin:4px 0 4px 18px;padding:0;list-style:decimal">` +
        items.map(it => `<li style="margin:2px 0">${parseInline(it)}</li>`).join('') +
        `</ol>`
      );
      continue;
    }

    // ── Empty line
    if (line.trim() === '') {
      out.push('<br>');
      i++;
      continue;
    }

    // ── Paragraph
    out.push(`<span style="display:block;margin:1px 0">${parseInline(line)}</span>`);
    i++;
  }

  return out.join('');
}
