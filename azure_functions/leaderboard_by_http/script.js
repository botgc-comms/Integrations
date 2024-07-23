// script.js

function combineResults(data1, data2) {
    return data1.map(player1 => {
        const player2 = data2.find(p => p.name === player1.name);
        if (player2) {
            const combinedPlayer = { ...player1 };
            if (player1.thru >= 18 && player2.thru > 0) {
                combinedPlayer.thru = 18 + player2.thru;
                combinedPlayer.total = player1.total + player2.total;
                combinedPlayer.final = `${handleNullValues(player1.final)}/${handleNullValues(player2.final)}`.replace(/\/$/, '');
            } else {
                combinedPlayer.total = player1.total;
                combinedPlayer.thru = player1.thru;
                combinedPlayer.final = handleNullValues(player1.final);
            }
            return combinedPlayer;
        }
        return player1;
    });
}

function fetchLeaderboard(compIds) {
    const compIdArray = compIds.split(',');
    if (compIdArray.length === 1) {
        return fetch(`${window.location.origin}/api/competition_result_by_http?compid=${compIdArray[0]}`)
            .then(response => response.json());
    } else {
        return Promise.all(compIdArray.map(compId =>
            fetch(`${window.location.origin}/api/competition_result_by_http?compid=${compId}`)
                .then(response => response.json())
        )).then(results => combineResults(results[0], results[1]));
    }
}

function handleNullValues(value) {
    if (value === null || value === undefined || value === '') {
        return '';
    }
    return value;
}

function updateCombinedLeaderboard() {
    const compIds = new URLSearchParams(window.location.search).get('compid');
    const scoreType = new URLSearchParams(window.location.search).get('scoreType') || "stroke";

    fetchLeaderboard(compIds)
        .then(data => {
            const leaderboardBody = document.getElementById('leaderboard-body');
            const existingRows = Array.from(leaderboardBody.children);

            // Sort data based on the total score, then by the total holes completed
            if (scoreType === 'stroke') {
                data.sort((a, b) => {
                    if (a.total === b.total) {
                        return b.thru - a.thru;
                    }
                    return a.total - b.total; // Ascending for stroke play
                });
            } else if (scoreType === 'points') {
                data.sort((a, b) => {
                    if (a.total === b.total) {
                        return b.thru - a.thru;
                    }
                    return b.total - a.total; // Descending for stableford
                });
            }

            let currentRank = 1;
            let rankGap = 1;
            let previousScore = data[0]?.total || null;

            data.forEach((player, index) => {
                if (index === 0 || player.total !== previousScore) {
                    currentRank += rankGap;
                    rankGap = 1;
                } else {
                    rankGap++;
                }

                const row = existingRows[index] || document.createElement('tr');
                const nameParts = player.name.split(' ');
                const surname = nameParts.pop();
                const firstName = nameParts.join(' ');
                const zeroDesc = (scoreType === "stroke") ? "Level" : "Highest"

                const parClass = player.total < 0 ? 'red-box' : 'black-box';
                const latestScoreDisplay = player.total === 0 ? zeroDesc : handleNullValues(player.total);

                row.innerHTML = `
                    <td class="rank-cell">${index === 0 || player.total !== previousScore ? currentRank - rankGap : ''}</td>
                    <td class="name-cell">${firstName} <strong>${surname}</strong></td>
                    <td class="handicap-cell"><span class="badge">${player.ph}</span></td>
                    <td class="score-cell">${handleNullValues(player.final)}</td>
                    <td class="par-cell"><div class="${parClass}">${latestScoreDisplay}</div></td>
                    <td class="thru-cell">${player.thru}</td>
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

document.addEventListener("DOMContentLoaded", () => {
    const urlParams = new URLSearchParams(window.location.search);
    const compName = urlParams.get('compname');
    const titleElement = document.getElementById('competition-title');
    console.log(compName)
    if (compName) {
        titleElement.innerHTML = compName.replace(/\\n/g, '<br>');
    }
});

updateCombinedLeaderboard();
setInterval(updateCombinedLeaderboard, 10000);
