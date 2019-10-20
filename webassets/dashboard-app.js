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
        // Look in the constants.js file for the flag friendly names for the dashboard
        // This will be a mapping from flag hash to friendly names.
        // If no mapping is found for a given flag hash, we'll make something up later and update this
        $scope.flagDashboardMapping = {};

        // The scores, on initialization, are an empty list.
        $scope.scores = {};
        $scope.scoresBack = {};
        $scope.team_names = {};
        $scope.flagDashboardNames = [];

        $scope.ScoresResource = $resource(API_ENDPOINT + "/score/:team");
    };

    $scope.PopulateScores = function () {
        for (i in TEAMS) {
            t = TEAMS[i];
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
            $timeout(function () {
                if ($scope.PopulateScores()) {
                    poll();
                }
            }, REFRESH_INTERVAL);
        };
        poll();
    };

    $scope.ScoresRefreshOnce = function () {
        $scope.PopulateScores();
    };

    $scope.ScorePresent = function () {
        $scope.scores = Object.keys($scope.scoresBack).map(function (key) {
            return { "team": key, "name": $scope.scoresBack[key].name, "score": $scope.scoresBack[key].score, "bitmask": $scope.scoresBack[key].bitmask };
        });
        $timeout(function () {
            $scope.ScorePresent();
        }, PRESENT_INTERVAL);
    };

    $scope.init();
    $scope.ScoresRefreshOnce();
    $scope.ScoresRefresh();

    // 5 seconds should be plenty for the initial scores to arrive, so wait that long and then
    // present them.
    $timeout(function () {
        $scope.ScorePresent();
    }, 5000);
}]);
