import "./GestureInstructions.css";

interface GestureInstructionsProps {
  onClose: () => void;
}

const STEPS: { title: string; body: string }[] = [
  {
    title: "Камера",
    body: "Убедитесь, что веб-камера подключена и не занята другим приложением (Zoom, OBS, браузер).",
  },
  {
    title: "Калибровка",
    body: "При первом включении пройдёт калибровка: голос попросит медленно сжать и разжать большой и указательный пальцы три раза — так определяется ваш личный порог «щипка».",
  },
  {
    title: "Наведение",
    body: "Поднесите руку к камере в удобной зоне перед собой. Курсор увеличится на 30% и начнёт следовать за рукой. Активна центральная часть кадра — так управление точнее.",
  },
  {
    title: "Клик и перетаскивание",
    body: "Сожмите большой и указательный пальцы — это нажатие. Не разжимая, двигайте рукой — это перетаскивание (drag). Разожмите — отпускание.",
  },
  {
    title: "Масштаб двумя руками",
    body: "Разведите обе руки в стороны — увеличение экрана (Ctrl+колесо), сведите — уменьшение.",
  },
  {
    title: "Голос работает параллельно",
    body: "Голосовые команды продолжают работать всё это время — можно одновременно управлять курсором рукой и говорить с ассистентом.",
  },
  {
    title: "Выключение",
    body: "Скажите «выключи режим жестов» или нажмите тумблер в разделе «Режимы». Камера сразу освобождается.",
  },
];

export function GestureInstructions({ onClose }: GestureInstructionsProps): JSX.Element {
  return (
    <div className="gesture-instr-overlay">
      <div className="gesture-instr-overlay__backdrop" onClick={onClose} />
      <div className="gesture-instr-panel" role="dialog" aria-modal="true" aria-label="Как пользоваться жестами">
        <h3 className="gesture-instr-panel__title">Как пользоваться управлением жестами</h3>
        <ol className="gesture-instr-panel__steps">
          {STEPS.map((step, index) => (
            <li className="gesture-instr-panel__step" key={step.title}>
              <span className="gesture-instr-panel__num">{index + 1}</span>
              <div>
                <p className="gesture-instr-panel__step-title">{step.title}</p>
                <p className="gesture-instr-panel__step-body">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="gesture-instr-panel__actions">
          <button type="button" className="gesture-instr-panel__close" onClick={onClose}>
            Понятно
          </button>
        </div>
      </div>
    </div>
  );
}
