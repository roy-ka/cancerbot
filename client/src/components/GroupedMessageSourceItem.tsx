import MessageSourceItem from './MessageSourceItem'
import type { Source } from '../types'

export default function GroupedMessageSourceItem({
  sources,
  displayTexts,
}: {
  sources: Source[]
  displayTexts: string[]
}) {
  return (
    <span>
      {sources.map((source, index) => (
        <span key={index}>
          <MessageSourceItem
            text={displayTexts[index] || source.text}
            source={source}
          />
          {index < sources.length - 1 && ', '}
        </span>
      ))}
    </span>
  )
}
