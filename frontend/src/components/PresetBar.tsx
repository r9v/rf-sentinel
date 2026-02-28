interface Preset {
  label: string;
  startMhz: number;
  stopMhz: number;
  antenna?: string;
}

interface Props {
  activeStart: number;
  activeStop: number;
  onSelect: (startMhz: number, stopMhz: number) => void;
}

interface PresetGroup {
  group: string;
  presets: Preset[];
}

const PRESET_GROUPS: PresetGroup[] = [
  {
    group: 'Broadcast & Utility',
    presets: [
      { label: 'FM Radio',  startMhz: 87.5,   stopMhz: 108.0,  antenna: 'Large, 4 sections (~87 MHz)' },
      { label: 'Airband',   startMhz: 118.0,   stopMhz: 137.0,  antenna: 'Large, 3 sections (~115 MHz)' },
      { label: 'PMR446',    startMhz: 446.0,   stopMhz: 446.2,  antenna: 'Small, 4 sections (~445 MHz)' },
      { label: 'ADS-B',     startMhz: 1089.0,  stopMhz: 1091.0, antenna: 'Small, 1 section (~1030 MHz)' },
    ],
  },
  {
    group: 'Ham Bands',
    presets: [
      { label: '10m',   startMhz: 28.0,    stopMhz: 29.7,   antenna: 'Large, 5 sections (~70 MHz)' },
      { label: '6m',    startMhz: 50.0,    stopMhz: 54.0,   antenna: 'Large, 5 sections (~70 MHz)' },
      { label: '2m',    startMhz: 144.0,   stopMhz: 148.0,  antenna: 'Large, 3 sections (~115 MHz)' },
      { label: '70cm',  startMhz: 430.0,   stopMhz: 440.0,  antenna: 'Small, 4 sections (~445 MHz)' },
      { label: '23cm',  startMhz: 1240.0,  stopMhz: 1300.0, antenna: 'Small, 1 section (~1030 MHz)' },
    ],
  },
  {
    group: 'IoT & ISM',
    presets: [
      { label: '433 ISM',   startMhz: 433.0,   stopMhz: 434.8, antenna: 'Small, 4 sections (~445 MHz)' },
      { label: '868 LoRa',  startMhz: 867.0,   stopMhz: 869.0, antenna: 'Small, 2 sections (~720 MHz)' },
      { label: 'GSM 900',   startMhz: 935.0,   stopMhz: 960.0, antenna: 'Small, 2 sections (~720 MHz)' },
    ],
  },
];

const presetBtn = 'px-2 py-1 text-xs rounded border transition-all';
const presetBtnActive = 'border-cyan-500/50 text-cyan-300 bg-cyan-500/10';
const presetBtnInactive = 'border-gray-700 text-gray-400 hover:border-gray-600 hover:text-gray-300';

export default function PresetBar({ activeStart, activeStop, onSelect }: Props) {
  return (
    <div className="space-y-2">
      {PRESET_GROUPS.map(g => (
        <div key={g.group}>
          <label className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 block">
            {g.group}
          </label>
          <div className="flex flex-wrap gap-1.5">
            {g.presets.map(p => (
              <button
                key={p.label}
                onClick={() => onSelect(p.startMhz, p.stopMhz)}
                title={p.antenna ? `🔌 ${p.antenna}` : undefined}
                className={`${presetBtn} ${activeStart === p.startMhz && activeStop === p.stopMhz ? presetBtnActive : presetBtnInactive}`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
