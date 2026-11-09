/* Small UI dictionary. Backend prompts are bilingual already; this only
   localizes the browser chrome, hints, and tool cards. */
(function () {
  const STORAGE_KEY = 'omnivoice.uiLang';

  const DICT = {
    zh: {
      'app.title': 'OmniVoice · 本地双语语音助手',
      'app.name': 'OmniVoice',
      'app.tagline': '本地运行 · Qwen3-Omni / MiniCPM-o 对比 · 25 个免密钥工具',
      'health.connecting': '连接中…',
      'health.ready': '就绪 · {name} 加载 {load}s',
      'health.loading': '模型加载中…',
      'health.offline': '服务未连接',
      'status.idle': '准备就绪',
      'status.listening': '正在听…',
      'status.transcribing': '正在识别…',
      'status.thinking': '正在思考…',
      'status.speaking': '正在说话…',
      'status.calibrating': '校准环境噪音',
      'status.speakNow': '直接说话',
      'status.recordingQuestion': '正在记录问题',
      'empty.title': '点一下麦克风，直接说话',
      'empty.examples': '试试：「北京今天天气怎么样？」<br>「TVF6410 现在飞到哪了？」<br>「美元兑人民币多少？」<br>「给我讲个笑话」',
      'controls.model': '模型',
      'controls.native': '原生语音',
      'controls.continuous': '连续对话',
      'controls.language': '语言',
      'controls.speaker': '音色',
      'controls.uiLang': '界面',
      'controls.records': '记录',
      'lang.auto': '自动',
      'lang.zh': '中文',
      'lang.en': 'EN',
      'mic.aria': '开始或结束录音',
      'mic.voiceInput': '语音输入',
      'input.placeholder': '也可以打字问…',
      'input.send': '发送',
      'hint.default': '点击麦克风开始录音，再次点击结束并发送',
      'hint.continuous': '连续对话已开启：直接说话，停顿约 1 秒自动发送',
      'hint.continuousNative': '连续对话 + 原生语音：直接说话，停顿约 1 秒自动发送',
      'hint.native.minicpm': '原生语音：音频送入 MiniCPM-o；Whisper 用于语种和工具路由',
      'hint.native.qwen': '原生语音：音频送入 Qwen3-Omni；Whisper 用于语种和工具路由',
      'title.model': '切换对比 Qwen3-Omni 与 MiniCPM-o 4.5',
      'title.native': '音频直接送入模型，跳过 Whisper（MiniCPM 仍用 Whisper 做语种/工具路由）',
      'title.continuous': '一直听，停顿后自动发送',
      'title.language': '自动只在中/英之间选择',
      'title.records': '下载每轮问答记录（转写、工具、回答、耗时）',
      'title.uiLang': '切换界面语言',
      'title.voiceMini': 'MiniCPM 使用参考音色（按语言自动选择）',
      'toast.mic': '无法访问麦克风：{err}',
      'toast.busy': '请等当前回答结束',
      'toast.continuous': '无法开启连续对话：{err}',
      'toast.noSpeech': '没有听清，请再说一次',
      'toast.modelSwitch': '已切换模型：首次请求会加载模型，请稍候',
      'toast.playBlocked': '浏览器阻止了播放，请再点一次',
      'error.transcribe': '转写失败',
      'error.answer': '回答失败',
      'role.you': '你',
      'role.native': '原生语音',
      'role.zh': '中文',
      'role.en': 'English',
      'weather.feels': '体感',
      'weather.humidity': '湿度',
      'weather.wind': '风速',
      'weather.unavailable': '天气数据不可用',
      'audio.play': '▶ 播放',
      'audio.pause': '⏸ 暂停',
      'audio.resume': '▶ 继续',
      'audio.replay': '▶ 重播',
      'timing.asr': '识别 {v}s',
      'timing.lang': '语种 {v}s',
      'timing.decide': '决策 {v}s',
      'timing.tool': '工具 {v}s',
      'timing.speech': '语音 {v}s',
      'flight.fallback': '航班',
      'flight.noSignal': '无实时信号',
      'flight.noSignalNote': '暂时没有这架航班的实时信号。',
      'flight.altitude': '高度',
      'flight.groundSpeed': '地速',
      'flight.heading': '航向',
      'flight.position': '位置',
      'flight.source': '实时 ADS-B 位置 · adsb.lol',
      'time.local': '本地时间',
      'fx.ecb': 'ECB 参考汇率',
      'wiki.fallback': '维基百科',
      'wiki.notFound': '没有找到相关条目。',
      'wiki.view': '在维基百科查看 →',
      'tool.failed': '工具查询失败：{err}',
      'assistant.empty': '（没有生成回答）',
      'mic.stopContinuous': '关闭连续对话',
    },
    en: {
      'app.title': 'OmniVoice · Local Bilingual Voice Assistant',
      'app.name': 'OmniVoice',
      'app.tagline': 'Local · Qwen3-Omni / MiniCPM-o · 25 keyless tools',
      'health.connecting': 'Connecting…',
      'health.ready': 'Ready · {name} loaded in {load}s',
      'health.loading': 'Loading model…',
      'health.offline': 'Server offline',
      'status.idle': 'Ready',
      'status.listening': 'Listening…',
      'status.transcribing': 'Transcribing…',
      'status.thinking': 'Thinking…',
      'status.speaking': 'Speaking…',
      'status.calibrating': 'calibrating noise floor',
      'status.speakNow': 'speak now',
      'status.recordingQuestion': 'recording question',
      'empty.title': 'Tap the mic and start talking',
      'empty.examples': 'Try: “What’s the weather in Beijing today?”<br>“Where is TVF6410 now?”<br>“USD to CNY?”<br>“Tell me a joke.”',
      'controls.model': 'Model',
      'controls.native': 'Native audio',
      'controls.continuous': 'Continuous',
      'controls.language': 'Language',
      'controls.speaker': 'Voice',
      'controls.uiLang': 'UI',
      'controls.records': 'Logs',
      'lang.auto': 'Auto',
      'lang.zh': '中文',
      'lang.en': 'EN',
      'mic.aria': 'Start or stop recording',
      'mic.voiceInput': 'Voice input',
      'input.placeholder': 'Or type a question…',
      'input.send': 'Send',
      'hint.default': 'Tap the mic to record; tap again to send',
      'hint.continuous': 'Continuous mode: just speak; sends after ~1s of silence',
      'hint.continuousNative': 'Continuous + native audio: just speak; sends after ~1s of silence',
      'hint.native.minicpm': 'Native audio: the clip goes to MiniCPM-o; Whisper handles language and tool routing',
      'hint.native.qwen': 'Native audio: the clip goes to Qwen3-Omni; Whisper handles language and tool routing',
      'title.model': 'Compare Qwen3-Omni and MiniCPM-o 4.5',
      'title.native': 'Send audio straight to the model, skipping Whisper (MiniCPM still uses Whisper for language/tool routing)',
      'title.continuous': 'Keep listening; send automatically after a pause',
      'title.language': 'Auto chooses between Chinese and English only',
      'title.records': 'Download per-turn logs (transcript, tool, answer, timings)',
      'title.uiLang': 'Switch UI language',
      'title.voiceMini': 'MiniCPM uses a reference voice chosen by language',
      'toast.mic': 'Cannot access the microphone: {err}',
      'toast.busy': 'Please wait for the current answer to finish',
      'toast.continuous': 'Cannot start continuous mode: {err}',
      'toast.noSpeech': 'Didn’t catch that — please say it again',
      'toast.modelSwitch': 'Model switched: the first request will load it, please wait',
      'toast.playBlocked': 'The browser blocked playback — tap play again',
      'error.transcribe': 'Transcription failed',
      'error.answer': 'Answer failed',
      'role.you': 'You',
      'role.native': 'native audio',
      'role.zh': 'Chinese',
      'role.en': 'English',
      'weather.feels': 'Feels',
      'weather.humidity': 'Humidity',
      'weather.wind': 'Wind',
      'weather.unavailable': 'Weather data unavailable',
      'audio.play': '▶ Play',
      'audio.pause': '⏸ Pause',
      'audio.resume': '▶ Resume',
      'audio.replay': '▶ Replay',
      'timing.asr': 'ASR {v}s',
      'timing.lang': 'Lang {v}s',
      'timing.decide': 'Decide {v}s',
      'timing.tool': 'Tool {v}s',
      'timing.speech': 'Speech {v}s',
      'flight.fallback': 'Flight',
      'flight.noSignal': 'No live signal',
      'flight.noSignalNote': 'No live signal for this flight right now.',
      'flight.altitude': 'Altitude',
      'flight.groundSpeed': 'Ground speed',
      'flight.heading': 'Heading',
      'flight.position': 'Position',
      'flight.source': 'Live ADS-B position · adsb.lol',
      'time.local': 'Local time',
      'fx.ecb': 'ECB reference rate',
      'wiki.fallback': 'Wikipedia',
      'wiki.notFound': 'No matching entry found.',
      'wiki.view': 'View on Wikipedia →',
      'tool.failed': 'Tool failed: {err}',
      'assistant.empty': '(no answer generated)',
      'mic.stopContinuous': 'Stop continuous mode',
    },
  };

  let lang = 'zh';
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && DICT[saved]) lang = saved;
  } catch (_) { /* private mode */ }
  // ?lang=en is handy for screenshots and sharing a link.
  try {
    const queryLang = new URLSearchParams(window.location.search).get('lang');
    if (queryLang && DICT[queryLang]) lang = queryLang;
  } catch (_) { /* no URLSearchParams */ }

  function t(key, vars) {
    const table = DICT[lang] || DICT.zh;
    let value = table[key];
    if (value == null) value = DICT.zh[key];
    if (value == null) return key;
    if (vars) {
      for (const [name, replacement] of Object.entries(vars)) {
        value = value.split(`{${name}}`).join(String(replacement));
      }
    }
    return value;
  }

  function apply() {
    document.querySelectorAll('[data-i18n]').forEach((node) => {
      node.textContent = t(node.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-html]').forEach((node) => {
      node.innerHTML = t(node.dataset.i18nHtml);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-title]').forEach((node) => {
      node.title = t(node.dataset.i18nTitle);
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach((node) => {
      node.setAttribute('aria-label', t(node.dataset.i18nAriaLabel));
    });
    document.title = t('app.title');
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    window.dispatchEvent(new CustomEvent('omnivoice:lang', { detail: { lang } }));
  }

  function setLang(next) {
    if (!DICT[next]) return;
    lang = next;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (_) { /* private mode */ }
    const sel = document.getElementById('uiLang');
    if (sel) sel.value = lang;
    apply();
  }

  function getLang() {
    return lang;
  }

  const sel = document.getElementById('uiLang');
  if (sel) {
    sel.value = lang;
    sel.addEventListener('change', () => setLang(sel.value));
  }
  apply();

  window.OmniI18n = { t, setLang, getLang, apply, dict: DICT };
})();
