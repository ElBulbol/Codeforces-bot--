import sqlite3
import sys

def update_user_scores(user_id: int, points: float):
    """
    Adds 'points' to overall_score, daily_score, weekly_score, monthly_score,
    and increments Number_of_problem_solved by 1.
    """
    try:
        conn = sqlite3.connect('db/db.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users
            SET
                overall_score = COALESCE(overall_score, 0) + ?,
                daily_score = COALESCE(daily_score, 0) + ?,
                weekly_score = COALESCE(weekly_score, 0) + ?,
                monthly_score = COALESCE(monthly_score, 0) + ?,
                Number_of_problem_solved = COALESCE(Number_of_problem_solved, 0) + 1
            WHERE user_id = ?
        ''', (points, points, points, points, user_id))
        conn.commit()
        print(f"Updated scores for user_id {user_id} (+{points})")
    except Exception as e:
        print(f"Error updating scores: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def update_user_score_in_challenge_participants(challenge_id: int, user_id: int, rating: int):
    """
    Adds (rating / 100) to score_awarded for the user in challenge_participants table.
    """
    score_awarded = rating / 100
    try:
        conn = sqlite3.connect('db/db.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE challenge_participants
            SET score_awarded = COALESCE(score_awarded, 0) + ?
            WHERE challenge_id = ? AND user_id = ?
        ''', (score_awarded, challenge_id, user_id))
        conn.commit()
        print(f"Updated score_awarded for user_id {user_id} in challenge_id {challenge_id} (+{score_awarded})")
    except Exception as e:
        print(f"Error updating score_awarded: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def update_contest_score(contest_id: int, user_id: int, problem_link: str):
    """
    Updates the score for a user in contest_participants and contest_scores tables.
    If the problem_link is not solved by anyone in the contest, add 10 points, else add 8 points.
    Also increments problem_solved in contest_scores by 1.
    """
    try:
        conn = sqlite3.connect('db/db.db')
        cursor = conn.cursor()

        # Check if anyone in this contest has solved this problem before
        cursor.execute('''
            SELECT solved_problems FROM contest_participants
            WHERE contest_id = ?
        ''', (contest_id,))
        rows = cursor.fetchall()
        problem_solved_by_anyone = False
        for row in rows:
            solved_problems = row[0] if row and row[0] else ""
            if solved_problems in (None, '', '[]'):
                continue
            # Split by comma and strip whitespace
            solved_list = [link.strip() for link in solved_problems.split(',') if link.strip()]
            # Check if problem_link matches any solved link
            if any(problem_link == solved for solved in solved_list):
                problem_solved_by_anyone = True
                break

        points = 8 if problem_solved_by_anyone else 10

        # Get this user's solved_problems
        cursor.execute('''
            SELECT solved_problems FROM contest_participants
            WHERE contest_id = ? AND user_id = ?
        ''', (contest_id, user_id))
        row = cursor.fetchone()
        solved_problems = row[0] if row and row[0] else ""

        if solved_problems in (None, '', '[]'):
            solved_problems_list = []
        else:
            solved_problems_list = [link.strip() for link in solved_problems.split(',') if link.strip()]

        already_solved = problem_link in solved_problems_list

        if not already_solved:
            solved_problems_list.append(problem_link)
            solved_problems_str = ','.join(solved_problems_list)
            cursor.execute('''
                UPDATE contest_participants
                SET solved_problems = ?
                WHERE contest_id = ? AND user_id = ?
            ''', (solved_problems_str, contest_id, user_id))

        # Update score in contest_participants
        cursor.execute('''
            UPDATE contest_participants
            SET score = COALESCE(score, 0) + ?
            WHERE contest_id = ? AND user_id = ?
        ''', (points, contest_id, user_id))

        # Update score and problem_solved in contest_scores
        cursor.execute('''
            UPDATE contest_scores
            SET score = COALESCE(score, 0) + ?,
                problem_solved = COALESCE(problem_solved, 0) + 1
            WHERE contest_id = ? AND user_id = ?
        ''', (points, contest_id, user_id))

        conn.commit()
        print(f"Contest score updated for user_id {user_id} in contest_id {contest_id} (+{points})")
    except Exception as e:
        print(f"Error updating contest score: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    # Replace with a valid user_id from your database
    test_user_id = 1
    test_points = 0
    test_rating = 800

    update_user_scores(test_user_id, test_points, test_rating)

    # Verify the update
    try:
        conn = sqlite3.connect('db/db.db')
        cursor = conn.cursor()
        cursor.execute('SELECT overall_score, daily_score, weekly_score, monthly_score, Number_of_problem_solved FROM users WHERE user_id = ?', (test_user_id,))
        result = cursor.fetchone()
        print("User scores after update:", result)
        conn.close()
    except Exception as e:
        print(f"Error verifying scores: {e}")

