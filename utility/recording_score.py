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

