import aiohttp
import random


async def get_random_problem(session: aiohttp.ClientSession, type_of_problem="random", rating=None, min_solved=None, max_retries=5):
    url = "https://codeforces.com/api/problemset.problems"
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
    except aiohttp.ClientError as e:
        print(f"Error fetching from Codeforces API: {e}")
        return None

    if data["status"] != "OK":
        print("Codeforces API error")
        return None

    problems = data["result"]["problems"]
    problem_statistics = data["result"]["problemStatistics"]
    
    # Create a mapping from (contestId, index) to solvedCount
    solved_count_map = {}
    for stat in problem_statistics:
        key = (stat["contestId"], stat["index"])
        solved_count_map[key] = stat.get("solvedCount", 0)
    
    # Retry logic for finding a suitable problem
    for attempt in range(max_retries):
        if type_of_problem.lower() == "random":
            # Get tags that have a reasonable number of problems
            tag_counts = {}
            for p in problems:
                for tag in p.get("tags", []):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            # Filter tags that have at least 10 problems to increase success rate
            viable_tags = [tag for tag, count in tag_counts.items() if count >= 10]
            if not viable_tags:
                viable_tags = list(tag_counts.keys())  # Fallback to all tags
            
            if not viable_tags:
                return None
                
            chosen_tag = random.choice(viable_tags)
            tagged = [p for p in problems if chosen_tag in [t.lower() for t in p.get("tags", [])]]
        else:
            required_tags = {t.strip().lower() for t in type_of_problem.split(',')}
            tagged = [p for p in problems if required_tags.issubset({t.lower() for t in p.get("tags", [])})]

        if not tagged:
            if type_of_problem.lower() != "random":
                return None  # No retry for specific tags
            continue  # Retry with different random tag

        # Handle rating filtering
        rating_filtered = tagged.copy()
        
        if isinstance(rating, str) and rating.lower() == "random":
            all_ratings = sorted({p["rating"] for p in tagged if "rating" in p})
            if all_ratings:
                selected_rating = random.choice(all_ratings)
                rating_filtered = [p for p in tagged if p.get("rating") == selected_rating]
            # If no ratings available, use all tagged problems
        elif rating is not None:
            try:
                rating_int = int(rating)
                rating_filtered = [p for p in tagged if p.get("rating") == rating_int]
            except (ValueError, TypeError):
                pass  # Keep all tagged if rating is not a valid int

        # Apply minimum solved count filter
        final_filtered = rating_filtered.copy()
        if min_solved is not None:
            try:
                min_solved_int = int(min_solved)
                final_filtered = []
                for p in rating_filtered:
                    problem_key = (p['contestId'], p['index'])
                    solved_count = solved_count_map.get(problem_key, 0)
                    if solved_count >= min_solved_int:
                        final_filtered.append(p)
            except (ValueError, TypeError):
                pass  # Keep all problems if min_solved is not a valid int

        if final_filtered:
            problem = random.choice(final_filtered)
            link = f"https://codeforces.com/contest/{problem['contestId']}/problem/{problem['index']}"
            print(f"Problem selected: {problem['name']} (Rating: {problem.get('rating', 'N/A')}) on attempt {attempt + 1}")

            # Get solved count from problemStatistics
            problem_key = (problem['contestId'], problem['index'])
            solved_count = solved_count_map.get(problem_key, 0)

            problem_data = {
                "name": problem["name"],
                "link": link,
                "tags": problem.get("tags", []),
                "rating": problem.get("rating", "N/A"),
                "solvedCount": solved_count
            }

            return problem_data
        
        # If rating filtering failed and we're using random tags, try again
        if type_of_problem.lower() != "random":
            break  # Don't retry for specific tags
    
    return None