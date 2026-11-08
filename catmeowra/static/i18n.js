(() => {
  const messages = {
    en: {
      subtitle: 'Live view and rolling recordings',
      connecting: '● Connecting', online: '● Live', offline: '● Camera offline', serviceOffline: '● Service offline',
      detectorStarting: '🐱 Starting detection', detectorError: '🐱 Detector error', catPresent: '🐱 Cat detected · {confidence}%', catAbsent: '🐱 No cat in view',
      rotateLeft: '↶ Rotate left', rotateRight: '↷ Rotate right', resetRotation: 'Reset rotation',
      storage: 'Recording storage', retentionLabel: 'Retention days (1–365)', saveRetention: 'Save retention period',
      recordingStatus: 'Recording status', catDetection: 'Cat detection', recordingProfile: 'Recording profile', segmentLength: 'Segment length', recentRecordings: 'Recent recordings',
      saveSnapshot: 'Save current snapshot', timelinePlayback: 'Timeline playback', loadingTimeline: 'Loading recording timeline…',
      lastHour: 'Last hour', last6Hours: 'Last 6 hours', last24Hours: 'Last 24 hours', today: 'Today',
      startTime: 'Start time', endTime: 'End time', playRange: 'Play selected range', timelineAria: 'Recording timeline', legacyRecordings: 'Legacy MP4 recordings',
      recording: 'Recording', preparing: 'Preparing', loading: 'Loading', seconds: '{value} sec', clips: '{value} clips', waitingFirst: 'Waiting for first segment',
      retentionSaved: 'Recordings will be retained for {days} days', saveFailed: 'Could not save: {error}',
      noLegacy: 'No legacy recordings.', legacyLoadFailed: 'Could not load legacy recordings.',
      timelineReady: '{count} continuous segments available', firstSegmentPending: 'Playback will be available after the first segment closes.',
      invalidRange: 'Choose a valid start and end time.', noHls: 'This browser does not support HLS playback.', loadingRange: 'Loading selected range…',
      playbackFailed: 'Playback failed: {error}', loadedRange: 'Loaded {seconds} seconds. Drag anywhere on the timeline.',
    },
    zh: {
      subtitle: '实时画面与滚动录像',
      connecting: '● 正在连接', online: '● 实时在线', offline: '● 摄像头离线', serviceOffline: '● 服务离线',
      detectorStarting: '🐱 正在启动识别', detectorError: '🐱 识别器出错', catPresent: '🐱 猫猫在 · {confidence}%', catAbsent: '🐱 猫猫不在画面',
      rotateLeft: '↶ 向左旋转', rotateRight: '↷ 向右旋转', resetRotation: '重置方向',
      storage: '录像存储', retentionLabel: '自动保留天数（1–365）', saveRetention: '保存覆盖时间',
      recordingStatus: '录像状态', catDetection: '猫咪识别', recordingProfile: '录像规格', segmentLength: '切片长度', recentRecordings: '最近录像',
      saveSnapshot: '保存当前照片', timelinePlayback: '时间轴回看', loadingTimeline: '读取录像时间线…',
      lastHour: '最近 1 小时', last6Hours: '最近 6 小时', last24Hours: '最近 24 小时', today: '今天',
      startTime: '开始时间', endTime: '结束时间', playRange: '播放所选时段', timelineAria: '录像时间轴', legacyRecordings: '旧版 MP4 录像',
      recording: '正在录像', preparing: '准备中', loading: '加载中', seconds: '{value} 秒', clips: '{value} 段', waitingFirst: '等待首段',
      retentionSaved: '已改为保留 {days} 天', saveFailed: '保存失败：{error}',
      noLegacy: '没有旧版录像。', legacyLoadFailed: '旧版录像读取失败。',
      timelineReady: '可回看 {count} 个连续片段', firstSegmentPending: '首段录像完成后即可回看',
      invalidRange: '请选择正确的开始和结束时间', noHls: '当前浏览器不支持 HLS 播放', loadingRange: '正在加载所选时段…',
      playbackFailed: '播放失败：{error}', loadedRange: '已载入 {seconds} 秒录像，可无缝拖动',
    },
  };

  const language = (navigator.languages?.[0] || navigator.language || 'en').toLowerCase();
  const locale = language.startsWith('zh') ? 'zh' : 'en';
  const t = (key, values = {}) => {
    const template = messages[locale][key] ?? messages.en[key] ?? key;
    return template.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? `{${name}}`);
  };
  const apply = () => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(element => { element.textContent = t(element.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach(element => { element.setAttribute('aria-label', t(element.dataset.i18nAria)); });
  };
  window.CatMeowraI18n = { locale, t, apply };
})();
