import MessageSourceItem from './MessageSourceItem'
import type { Source } from '../types'

export default function GroupedMessageSourceItem({
  sources,
  displayTexts,
  onAskAboutSource,
}: {
  sources: Source[]
  displayTexts: string[]
  onAskAboutSource?: (sourceId: string) => void
}) {
  return (
    <span>
      {sources.map((source, index) => (
        <span key={index}>
          <MessageSourceItem
            text={displayTexts[index] || source.text}
            source={source}
            onAskAboutSource={onAskAboutSource}
          />
          {index < sources.length - 1 && ', '}
        </span>
      ))}
    </span>
  )
}
