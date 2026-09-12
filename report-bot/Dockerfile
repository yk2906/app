FROM golang:1.27-alpine AS builder
WORKDIR /src

COPY go.mod ./
RUN go mod download

COPY *.go ./
RUN CGO_ENABLED=0 go build -o /out/report-bot .

FROM gcr.io/distroless/static-debian12
COPY --from=builder /out/report-bot /report-bot

EXPOSE 8080
ENTRYPOINT ["/report-bot"]
