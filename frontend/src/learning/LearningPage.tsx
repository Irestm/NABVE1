import { useState } from "react";
import { EnglishCourse } from "./english/EnglishCourse";
import "./LearningPage.css";

interface Course {
  id: string;
  title: string;
  subtitle: string;
}

const COURSES: Course[] = [{ id: "english", title: "English", subtitle: "Слова из сериалов" }];

export function LearningPage(): JSX.Element {
  const [courseId, setCourseId] = useState(COURSES[0]?.id ?? "english");

  return (
    <div className="ql">
      <nav className="ql-courses" aria-label="Курсы">
        {COURSES.map((course) => (
          <button
            key={course.id}
            type="button"
            className={course.id === courseId ? "ql-course ql-course--active" : "ql-course"}
            onClick={() => setCourseId(course.id)}
            aria-current={course.id === courseId}
          >
            <span className="ql-course__title">{course.title}</span>
            <span className="ql-course__subtitle">{course.subtitle}</span>
          </button>
        ))}
      </nav>
      {courseId === "english" && <EnglishCourse />}
    </div>
  );
}
