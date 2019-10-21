var myApp = angular.module('dashboardApp', ['ngResource']);

var REFRESH_INTERVAL = 5000;
var PRESENT_INTERVAL = 5000;

myApp.filter("toArray", function () {
    return function (obj) {
        var result = [];
        angular.forEach(obj, function (val, key) {
            result.push({ "team": key, "score": val });
        });
        return result;
    };
});

myApp.controller('scoreboardController', ['$scope', '$rootScope', '$resource', '$timeout', function ($scope, $rootScope, $resource, $timeout) {

    $scope.init = function () {
        // The scores, on initialization, are an empty list.
        $scope.scores = {};
        $scope.scoresBack = {};
        $scope.team_names = {};
        $scope.flagDashboardNames = [];

        $scope.teams = [];
        fetch("teams.json")
            .then(response => response.json())
            .then(function (rjson) { $scope.teams = rjson; });


        $scope.ScoresResource = $resource(API_ENDPOINT + "/score/:team");
    };

    $scope.PopulateScores = function () {
        for (i in $scope.teams) {
            t = $scope.teams[i];
            team_id = null;
            if (typeof (t) == "object") {
                team_id = t.team_id;
                team_name = t.team_name;
                $scope.team_names[team_id] = team_name;
            }
            else {
                team_id = t;
                team_name = t.toString();
                $scope.team_names[team_id] = team_name;
            }
            // For each team, retrieve the score for that team.
            $scope.ScoresResource.get({
                team: team_id.toString()
            }, function (score) {
                $scope.scoresBack[score.team] = {
                    id: score.team,
                    name: $scope.team_names[score.team],
                    score: score.score,
                    bitmask: score.bitmask.map(function (flag) {
                        return flag.claimed;
                    })
                };
                $scope.flagDashboardNames = score.bitmask.map(function (flag) {
                    return flag.nickname;
                });
            });
        }
        return true;
    }

    $scope.ScoresRefresh = function () {
        var poll = function () {
            var call_again_in = REFRESH_INTERVAL;

            if ($scope.teams.length == 0 || $scope.scores.length == 0 || $scope.scores.length < $scope.teams.length) {
                call_again_in = 250;
            }

            $timeout(function () {
                if ($scope.PopulateScores()) {
                    poll();
                }
            }, call_again_in);
        };
        poll();
    };

    $scope.ScoresRefreshOnce = function () {
        $scope.PopulateScores();
    };

    $scope.ScorePresent = function () {
        fetch("teams.json")
            .then(response => response.json())
            .then(function (rjson) { $scope.teams = rjson; });

        $scope.scores = Object.keys($scope.scoresBack).map(function (key) {
            return { "team": key, "name": $scope.scoresBack[key].name, "score": $scope.scoresBack[key].score, "bitmask": $scope.scoresBack[key].bitmask };
        });

        var call_again_in = PRESENT_INTERVAL;

        if ($scope.teams.length == 0 || $scope.scores.length == 0 || $scope.scores.length < $scope.teams.length) {
            call_again_in = 250;
        }

        $timeout(function () {
            $scope.ScorePresent();
        }, call_again_in);
    };

    $scope.init();
    $scope.ScoresRefreshOnce();
    $scope.ScoresRefresh();

    // 5 seconds should be plenty for the initial scores to arrive, so wait that long and then
    // present them.
    $timeout(function () {
        $scope.ScorePresent();
    }, 250);
}]);
