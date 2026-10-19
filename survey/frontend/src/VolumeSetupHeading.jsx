export default function VolumeSetupHeading({ config, screeningEnabled }) {
  const enabled = screeningEnabled ?? config?.headphone_screening_enabled
  return <><p className="p-eyebrow">{enabled === false ? 'LISTENING SETUP' : 'SETUP · 1 OF 2'}</p><h1>Find a comfortable level.</h1><p className="p-lede">Start with a low device volume, play the tone and adjust it to a comfortable level. Keep that setting for the rest of the session.</p></>
}
