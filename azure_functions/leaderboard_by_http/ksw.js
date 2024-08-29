// script.js

function fetchLeaderboard() {
    return fetch(`${window.location.origin}/api/ksw_result_by_http`)
        .then(response => response.json());
}

function handleNullValues(value) {
    if (value === null || value === undefined || value === '') {
        return '';
    }
    return value;
}

function updateLeaderboard() {
    
    fetchLeaderboard()
        .then(data => {

            const leaderboardBody = document.getElementById('leaderboard-body');
            const existingRows = Array.from(leaderboardBody.children);

            // Sort data based on the total score, then by the total holes completed
            data.sort((a, b) => {
                return b.Score - a.Score; 
            });

            let currentRank = 1;
            let rankGap = 1;
            let previousScore = data[0]?.Score || null;

            data.slice(0, 50).forEach((player, index) => {
                if (index === 0 || player.Score !== previousScore) {
                    currentRank += rankGap;
                    rankGap = 1;
                } else {
                    rankGap++;
                }

                const row = existingRows[index] || document.createElement('tr');
                const nameParts = player.Player.split(' ');
                const surname = nameParts.pop();
                const firstName = nameParts.join(' ');
                const zeroDesc = "Highest"

                const parClass = player.Score < 0 ? 'red-box' : 'black-box';
                let latestScoreDisplay = player.Score === 0 ? zeroDesc : handleNullValues(player.Score);
                if (player.Score > 0) latestScoreDisplay = latestScoreDisplay

                const scoreCellContent = player.r1 !== undefined && player.r2 !== undefined
                    ? `${player.r1}/${player.r2}`
                    : handleNullValues(player.Score);

                const rank = player.r1 !== undefined && player.r2 !== undefined
                    ? player.position
                    : index === 0 || player.Score !== previousScore ? currentRank - rankGap : ''

                row.innerHTML = `
                    <td class="rank-cell">${rank}</td>
                    <td class="name-cell">${firstName} <strong>${surname}</strong></td>
                    <td class="par-cell"><div class="${parClass}">${latestScoreDisplay}</div></td>
                    <td class="thru-cell">${player.Played}</td>
                `;

                // Remove animation classes if they exist
                row.classList.remove('moving-up', 'moving-down');

                // Determine if the row is moving up or down
                if (existingRows[index]) {
                    const currentPos = existingRows.indexOf(row);
                    if (currentPos !== index) {
                        row.classList.add(currentPos > index ? 'moving-up' : 'moving-down');
                    }
                }

                if (!existingRows[index]) {
                    leaderboardBody.appendChild(row);
                }

                previousScore = player.total;
            });

            // Remove extra rows if any
            while (leaderboardBody.children.length > data.length) {
                leaderboardBody.removeChild(leaderboardBody.lastChild);
            }
        })
        .catch(error => console.error('Error fetching leaderboard data:', error));
}

updateLeaderboard();
setInterval(updateLeaderboard, 10000);
